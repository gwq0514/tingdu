"""Local microphone recordings. Complete WAV chunks are durable before ASR runs."""
import hashlib
import io
import json
import re
import uuid
import threading
import wave
import shutil
import live_speakers
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from fastapi import HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
import audio_processing

_locks = {}
_guard = threading.Lock()
MAX_SECONDS = 8 * 3600

def recording_lock(jid):
    with _guard:
        return _locks.setdefault(jid, threading.RLock())

@contextmanager
def deletion_lock(jid, cloud=False):
    lock=recording_lock(jid)
    acquired=lock.acquire(timeout=2) if cloud else lock.acquire()
    if not acquired:raise HTTPException(409,'录音仍在保存或整理，请等待后台处理完成后再删除；本次未删除任何文件。')
    try:yield
    finally:lock.release()

class StartMeeting(BaseModel):
    title: str = Field(default='', max_length=120)
    project: str = Field(default='', max_length=60)
    model: str = 'sensevoice'
    llm_model: str = Field(default='', max_length=200)

class FinishMeeting(BaseModel):
    chunks: int = Field(ge=0, le=9000)

class RenameMeeting(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    project: str | None = Field(default=None, max_length=60)

class ReprocessRecording(BaseModel):
    denoise: bool = True
    diarization: bool = True

class RecordingProject(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def register(app, engine):
    def projects():
        path = engine.metadata_dir() / 'recording-projects.json'
        return json.loads(path.read_text()) if path.exists() else []

    def validate_project(name):
        if not name: return ''
        name = name.strip()
        if name not in projects():
            raise HTTPException(400, '请先新建该项目，再将记录归入项目')
        return name

    @app.get('/api/recording-projects')
    def list_projects():
        return projects()

    @app.post('/api/recording-projects')
    def add_project(req: RecordingProject):
        name = req.name.strip()
        if not name or name in ('.', '..', '未分类') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
            raise HTTPException(400, '项目名称不能为空，不能使用文件路径符号；未分类表示没有归入项目')
        with _guard:
            names = projects()
            existing = next((p for p in names if p.casefold() == name.casefold()), None)
            if existing: return {'name':existing}
            if len(names) >= 500: raise HTTPException(400, '最多可创建500个项目')
            names.append(name)
            path = engine.metadata_dir() / 'recording-projects.json'
            temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            temp.write_text(json.dumps(names, ensure_ascii=False)); temp.replace(path)
        return {'name':name}

    def meeting(jid):
        rec = engine.read(jid)
        if rec.get('source') != 'meeting':
            raise HTTPException(404, '找不到录音记录')
        return rec

    def configure_audio(rec,denoise=True,diarize=True):
        status=audio_processing.model_status(engine.DATA)
        rec.update(noise_suppression_requested=denoise,noise_suppression=denoise and status['denoise_available'],noise_suppression_model='GTCRN',noise_suppression_status=('pending' if status['denoise_available'] else 'unavailable') if denoise else 'off',diarization_requested=diarize,diarization=False,diarization_model=status['diarization_model'],diarization_status=('queued' if status['diarization_available'] else 'unavailable') if diarize else 'off')

    def transcribe_chunk(jid, sequence):
        root = engine.folder(jid)
        chunk_path = root / 'chunks' / f'{sequence:05d}.wav'
        enhancement='off'
        try:
            import numpy as np
            with wave.open(str(chunk_path), 'rb') as audio:
                samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            original_samples=samples.copy()
            rec = meeting(jid)
            rec['asr_model'] = 'sensevoice'
            enhancement='off'
            if rec.get('noise_suppression'):
                try:
                    prefix=audio_processing.read_wav(root/'chunks'/f'{sequence-1:05d}.wav')[-8000:] if sequence else None
                    clean=engine.audio_models(live=True).enhance(samples,prefix)
                    audio_processing.write_wav(chunk_path.with_suffix('.enhanced.wav'),clean)
                    samples=clean
                    enhancement='done'
                except Exception:enhancement='error'
            with engine.asr_lock():
                segments, _ = engine.shared_asr(live=True).transcribe(samples)
                offset = rec['recording_chunks'][sequence]['start']
                result=[]
                for segment in segments:
                    if not segment.text.strip():continue
                    row={'start':round(offset+segment.start,2),'end':round(offset+segment.end,2),'text':segment.text.strip()}
                    if getattr(segment,'text_corrections',None):
                        row.update(raw_text=segment.raw_text,text_corrections=segment.text_corrections)
                    words=getattr(segment,'words',None) or []
                    if words:row['words']=[{'start':round(offset+w.start,3),'end':round(offset+w.end,3),'word':w.word} for w in words]
                    result.append(row)
            with recording_lock(jid):
                rec = meeting(jid)
                rec['recording_chunks'][sequence].update(state='done', segments=result,asr_segments=result,enhancement=enhancement)
                rebuild_text(rec)
                engine.save(rec)
            if rec.get('diarization_requested') and rec.get('diarization_status')!='unavailable' and result:
                try:
                    labeled,count=engine.speaker_service().process(jid,original_samples,result,offset)
                    live_status='done'
                except Exception:
                    labeled=[dict(row,speaker='未确定',speaker_uncertain=True,speaker_provisional=True) for row in result]
                    count=rec.get('live_speaker_count',0);live_status='error'
                with recording_lock(jid):
                    rec=meeting(jid)
                    rec['recording_chunks'][sequence]['segments']=labeled
                    rec.update(live_diarization_status=live_status,live_speaker_count=count)
                    rebuild_text(rec);engine.save(rec)
        except Exception:
            with recording_lock(jid):
                rec = meeting(jid)
                rec['recording_chunks'][sequence].update(state='error',enhancement=enhancement)
                engine.save(rec)
        finally:
            engine.recording_priority.completed(jid)

    def rebuild_text(rec):
        rec['segments'] = [s for c in rec['recording_chunks'] for s in c.get('segments', [])]
        rec['text'] = '\n'.join(s['text'] for s in rec['segments'])
        rec['asr_segments'] = [s for c in rec['recording_chunks'] for s in c.get('asr_segments',c.get('segments',[]))]
        rec['raw_asr_text'] = '\n'.join(s.get('raw_text',s['text']) for s in rec['asr_segments'])
        rec['transcribed_chunks'] = sum(c.get('state') == 'done' for c in rec['recording_chunks'])
        rec['failed_chunks'] = sum(c.get('state') == 'error' for c in rec['recording_chunks'])
        if rec.get('noise_suppression'):
            rec['noise_suppression_status']='fallback' if any(c.get('enhancement')=='error' for c in rec['recording_chunks']) else 'done' if rec['recording_chunks'] and all(c.get('state') in ('done','error') for c in rec['recording_chunks']) else 'running'

    def assemble(rec,enhanced=False):
        root = engine.folder(rec['id'])
        name='enhanced' if enhanced else 'source'
        temp = root / (name+'.partial.wav')
        with wave.open(str(temp), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
            for index in range(len(rec['recording_chunks'])):
                path=root/'chunks'/f'{index:05d}.wav'
                clean=path.with_suffix('.enhanced.wav')
                if enhanced and clean.exists():path=clean
                with wave.open(str(path), 'rb') as chunk:
                    output.writeframes(chunk.readframes(chunk.getnframes()))
        temp.replace(root / (name+'.wav'))
        if not enhanced:rec['media_file'] = 'source.wav'

    def finish_job(jid):
        try:
            with recording_lock(jid):
                rec = meeting(jid)
                assemble(rec); rebuild_text(rec)
                if rec.get('noise_suppression'):assemble(rec,enhanced=True)
                rec['status'] = 'done'
                if rec.get('failed_chunks'):
                    rec['message'] = '原声已保存，部分片段转写失败，可重试完整转写。'
                elif not rec['text']:
                    rec['message'] = '原声已保存，未识别到语音。可回听检查或重试完整转写。'
                else:
                    rec['message'] = '原声与转写已保存。'
                if rec.get('llm_model') and rec['text'] and not rec.get('failed_chunks'):
                    rec['summary_status'] = 'running'
                engine.save(rec)
            engine.speaker_service().clear(jid)
            if rec.get('summary_status') == 'running' or rec.get('diarization_status')=='queued':
                engine.pool.submit(summarize_job,jid,rec.get('llm_model',''))
        except Exception:
            with recording_lock(jid):
                rec = meeting(jid); rec.update(status='error', message='录音整理未完成，录音片段已保留，可重试恢复。')
                engine.save(rec)

    def summarize_job(jid,model):
        engine.recording_priority.wait_for_background()
        rec=meeting(jid)
        if rec.get('diarization_status')=='queued':
            with recording_lock(jid):
                rec=meeting(jid);rec['diarization_status']='running';engine.save(rec)
            try:
                turns=engine.diarize_file(engine.folder(jid)/'source.wav',engine.recording_priority.wait_for_background)
                with recording_lock(jid):
                    rec=meeting(jid)
                    if turns:
                        rec['segments']=audio_processing.label_segments(rec.get('asr_segments',rec['segments']),turns)
                        rec['text']='\n'.join(s['text'] for s in rec['segments'])
                    rec.update(diarization=bool(turns),diarization_status='done' if turns else 'empty',speaker_turns=turns,speaker_count=len(set(t['speaker_id'] for t in turns)))
                    engine.save(rec)
            except Exception:
                with recording_lock(jid):
                    rec=meeting(jid);rec['diarization_status']='error';rec['message']='原声与文字已保存，发言人区分未完成，可稍后重新处理。';engine.save(rec)
        rec=meeting(jid)
        if model and rec.get('summary_status')=='running':
            engine.recording_priority.wait_for_background()
            try:engine.chat(jid,engine.ChatRequest(model=model,summary=True))
            except Exception:
                with recording_lock(jid):
                    rec=meeting(jid);rec['summary_status']='error';rec['message']='原声与转写已保存，内容总结生成失败，可稍后重试。';engine.save(rec)

    def retry_job(jid):
        try:
            engine.recording_priority.wait_for_background()
            with recording_lock(jid):
                rec=meeting(jid);assemble(rec);engine.save(rec)
            source=engine.folder(jid)/'source.wav';asr_source=source
            if rec.get('noise_suppression'):
                try:
                    engine.audio_models().enhance_file(source,engine.folder(jid)/'enhanced.wav',engine.recording_priority.wait_for_background)
                    asr_source=engine.folder(jid)/'enhanced.wav';noise_status='done'
                except Exception:noise_status='fallback'
                with recording_lock(jid):
                    rec=meeting(jid);rec['noise_suppression_status']=noise_status;engine.save(rec)
            engine.process(jid,'',str(asr_source),rec['asr_model'],'')
            with recording_lock(jid):
                rec=meeting(jid);rec['media_file']='source.wav'
                if rec['status']=='done':
                    rec['failed_chunks']=0;rec['message']='完整原声已重新处理，正在整理发言人。' if rec.get('diarization_status')=='queued' else '完整原声已重新转写。'
                engine.save(rec)
            if rec['status']=='done':summarize_job(jid,'')
        except Exception:
            rec=meeting(jid);rec.update(status='error',message='重新处理未完成，原声和已有文字均已保留。');engine.save(rec)

    @app.get('/meetings')
    def page(embedded: bool = False):
        if not embedded: return RedirectResponse('/?view=recordings', status_code=307)
        if engine.LOW_MEMORY:
            from cloud_ui import page as cloud_page
            return cloud_page(engine.ROOT / 'static' / 'meetings.html')
        return FileResponse(engine.ROOT / 'static' / 'meetings.html')

    @app.get('/api/meetings')
    def history():
        return [r for r in engine.jobs() if r.get('source') == 'meeting']

    @app.get('/api/audio-models')
    def audio_models():
        from sensevoice_asr import available
        return dict(audio_processing.model_status(engine.DATA),asr_model='SenseVoiceSmall INT8',asr_available=available(engine.DATA))

    @app.get('/api/meetings/{jid}/enhanced')
    def enhanced_audio(jid:str):
        meeting(jid);path=engine.folder(jid)/'enhanced.wav'
        if not path.is_file():raise HTTPException(404,'尚无降噪音频')
        return FileResponse(path,media_type='audio/wav',filename='enhanced.wav')

    @app.post('/api/meetings')
    def start(req: StartMeeting):
        if req.model != 'sensevoice':
            raise HTTPException(400, '录音转写固定使用 SenseVoiceSmall INT8 模型')
        from sensevoice_asr import available
        if not available(engine.DATA):
            raise HTTPException(400, '转写模型尚未安装，请先安装后录音')
        if req.llm_model and req.llm_model not in engine.health()['models']:
            raise HTTPException(400, '所选内容总结模型未就绪，可选择仅保存转写')
        if engine.LOW_MEMORY and engine.recording_priority.busy():
            raise HTTPException(409,'试运行期间一次接收一场录音，请先结束当前录音并等待片段保存完成。')
        project = validate_project(req.project)
        rec = engine.new(req.title.strip() or '录音 ' + datetime.now().astimezone().strftime('%m月%d日 %H:%M'), 'meeting')
        rec.update(project=project, status='recording', message='正在录音，文字分段更新…', asr_model=req.model, llm_model=req.llm_model, recording_chunks=[], transcribed_chunks=0, failed_chunks=0, duration=0, summary_status='none', diarization=False)
        configure_audio(rec)
        (engine.folder(rec['id']) / 'chunks').mkdir()
        engine.save(rec)
        engine.recording_priority.start(rec['id'])
        return rec

    @app.post('/api/meetings/{jid}/chunks')
    async def upload_chunk(jid: str, sequence: int = Form(...), file: UploadFile = File(...)):
        if sequence < 0 or sequence >= 9000:
            raise HTTPException(400, '录音片段编号无效')
        raw = await file.read(640045)
        if len(raw) > 640044:
            raise HTTPException(413, '单次录音片段不能超过20秒')
        try:
            with wave.open(io.BytesIO(raw), 'rb') as audio:
                frames = audio.getnframes()
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, 'NONE') or not 0 < frames <= 320000:
                    raise ValueError()
                if len(audio.readframes(frames)) != frames * 2:
                    raise ValueError()
        except (wave.Error, EOFError, ValueError):
            raise HTTPException(400, '录音格式无效，请使用16kHz单声道PCM WAV')
        digest = hashlib.sha256(raw).hexdigest()
        with recording_lock(jid):
            rec = meeting(jid); chunks = rec['recording_chunks']
            if sequence < len(chunks):
                if chunks[sequence]['sha256'] != digest:
                    raise HTTPException(409, '该编号已保存不同的录音，请勿覆盖')
                return {'ok':True, 'duplicate':True, 'sequence':sequence}
            if rec['status'] != 'recording':
                raise HTTPException(409, '录音已经结束，不能追加录音')
            if sequence != len(chunks):
                raise HTTPException(409, '录音片段顺序不连续，请重试上一片段')
            total_frames = sum(c['frames'] for c in chunks)
            if total_frames + frames > (600 if engine.cloud_mode() else MAX_SECONDS) * 16000:
                raise HTTPException(413, '云端单次录音最多10分钟，请结束后开始新录音' if engine.cloud_mode() else '单次录音最多录制8小时，请结束后开始新会议')
            target = engine.folder(jid) / 'chunks' / f'{sequence:05d}.wav'
            temp = target.with_suffix('.tmp'); temp.write_bytes(raw); temp.replace(target)
            chunks.append({'frames':frames, 'start':total_frames/16000, 'sha256':digest, 'state':'queued'})
            rec['duration'] = (total_frames + frames)/16000
            engine.save(rec)
            engine.recording_priority.enqueue(jid)
            try:engine.recording_pool.submit(transcribe_chunk, jid, sequence)
            except Exception:
                engine.recording_priority.completed(jid)
                rec['recording_chunks'][sequence]['state']='error'
                rebuild_text(rec);engine.save(rec)
                raise HTTPException(503,'录音转写队列不可用，原声片段已保存，请结束后重新转写')
        return {'ok':True, 'sequence':sequence}

    @app.post('/api/meetings/{jid}/finish')
    def finish(jid: str, req: FinishMeeting):
        with recording_lock(jid):
            rec = meeting(jid)
            if req.chunks != len(rec['recording_chunks']):
                raise HTTPException(409, '还有录音片段未保存，请先重试保存')
            if rec['status'] != 'recording':
                return rec
            engine.recording_priority.stop(jid)
            rec.update(status='running', ended_at=datetime.now(timezone.utc).isoformat(), message='录音已结束，正在整理文字与内容总结…')
            if not req.chunks:
                rec.update(status='error', message='这次录音没有收到音频，请重新开始录音。')
                engine.save(rec); return rec
            engine.save(rec); engine.recording_pool.submit(finish_job, jid)
        return rec

    @app.post('/api/meetings/{jid}/retry')
    def retry(jid: str,req:ReprocessRecording|None=None):
        with recording_lock(jid):
            rec = meeting(jid)
            if rec['status'] not in ('done', 'error') or rec.get('diarization_status') in ('queued','running'):
                raise HTTPException(409, '请先结束录音或等待处理完成')
            if rec.get('audio_deleted'):raise HTTPException(409, '音频已删除，无法重新处理')
            if not rec['recording_chunks']:
                raise HTTPException(400, '没有已保存的录音片段')
            from sensevoice_asr import available
            if not available(engine.DATA):raise HTTPException(400, 'SenseVoice 模型尚未安装，原记录未修改')
            options=req or ReprocessRecording()
            configure_audio(rec,options.denoise,options.diarization)
            rec.update(asr_model='sensevoice', status='running', summary_status='none', summary='', message='正在用 SenseVoice 重新转写完整录音…'); engine.save(rec)
            engine.pool.submit(retry_job, jid)
            return rec

    @app.delete('/api/meetings/{jid}')
    def delete_recording(jid:str,audio_only:bool=False):
        with deletion_lock(jid,engine.LOW_MEMORY):
            rec=meeting(jid)
            if rec['status'] not in ('done','error') or rec.get('diarization_status') in ('queued','running') or rec.get('summary_status')=='running':
                raise HTTPException(409,'请先结束录音并等待转写、发言人和总结处理完成后再删除')
            with engine.active_chat_lock:
                if engine.active_chats.get(jid):raise HTTPException(409, '正在生成总结或回答问题，请完成后再删除')
            root=engine.folder(jid)
            staging=engine.DATA/'.deleting'/uuid.uuid4().hex
            staging.parent.mkdir(exist_ok=True)
            engine.speaker_service().clear(jid)
            if not audio_only:
                root.replace(staging)
                shutil.rmtree(staging)
                return {'id':jid,'deleted':'record'}
            if rec.get('audio_deleted'):return {'id':jid,'deleted':'audio'}
            staging.mkdir()
            moved=[]
            try:
                for path in root.iterdir():
                    if path.name=='chunks' or path.suffix.lower() in ('.wav','.mp3','.m4a','.aac','.flac','.ogg','.mp4','.webm','.mkv','.mov'):
                        path.replace(staging/path.name);moved.append(path.name)
                rec.update(audio_deleted=True,media_file='',noise_suppression_status='off',message='音频已删除，转写与总结保留。')
                engine.save(rec)
            except Exception:
                for name in moved:(staging/name).replace(root/name)
                staging.rmdir()
                raise
            shutil.rmtree(staging)
            return {'id':jid,'deleted':'audio'}

    @app.patch('/api/meetings/{jid}')
    def rename(jid: str, req: RenameMeeting):
        title = req.title.strip() if req.title is not None else None
        if title is not None and not title: raise HTTPException(400, '记录名称不能为空')
        project = validate_project(req.project) if req.project is not None else None
        with recording_lock(jid):
            rec = meeting(jid)
            if title is not None: rec['title'] = title
            if project is not None: rec['project'] = project
            rec['metadata_revision']=rec.get('metadata_revision',0)+1
            engine.save(rec)
        return rec

    @app.on_event('startup')
    def recover():
        for path in engine.DATA.glob('*/record.json'):
            rec = engine.read(path.parent.name)
            if rec.get('source')=='meeting' and rec.get('status')!='recording' and rec.get('diarization_status') in ('queued','running'):
                rec['diarization_status']='error';rec['message']='发言人处理曾被中断，原声与文字仍保留，可重新处理。';engine.save(rec)
            if rec.get('source') == 'meeting' and rec.get('status') == 'recording':
                # Recover only audio actually received before interruption.
                try:
                    if rec.get('recording_chunks'):
                        assemble(rec); rebuild_text(rec)
                    rec.update(status='error', message='上次录音被中断，已接收的原声和文字已保留，可重试完整转写。')
                    engine.save(rec)
                except Exception:
                    rec.update(status='error', message='上次录音被中断，录音片段仍保留在本机。'); engine.save(rec)
