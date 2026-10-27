"""Small CPU-only speech enhancement and anonymous speaker diarization.
Weights are installed explicitly; inference never downloads or uploads audio.
"""
from functools import lru_cache
import hashlib
import bisect
import threading
import wave
from pathlib import Path
import numpy as np

ASSETS={
 'gtcrn.onnx':{'sha256':'e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534','url':'https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx'},
 'speaker-segmentation.onnx':{'sha256':'d582f4b4c6b48205de7e0643c57df0df5615a3c176189be3fc461e9d18827b5d','url':'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2','member':'model.int8.onnx'},
 'speaker-embedding.onnx':{'sha256':'1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b','url':'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx'},
}

@lru_cache(maxsize=32)
def _verified(filename,size,mtime):
    return hashlib.sha256(Path(filename).read_bytes()).hexdigest()==ASSETS[Path(filename).name]['sha256']

def model_status(data):
    import importlib.util
    runtime=importlib.util.find_spec('sherpa_onnx') is not None
    root=Path(data)/'models'/'audio'
    good={}
    for name in ASSETS:
        path=root/name
        good[name]=path.is_file() and _verified(str(path.resolve()),path.stat().st_size,path.stat().st_mtime_ns)
    return {'denoise_available':runtime and good['gtcrn.onnx'],'diarization_available':runtime and good['speaker-segmentation.onnx'] and good['speaker-embedding.onnx'],'denoise_model':'GTCRN','diarization_model':'pyannote segmentation 3.0 + 3D-Speaker ERes2Net','local_only':True}

def read_wav(path):
    with wave.open(str(path),'rb') as audio:
        if (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())!=(16000,1,2):
            raise ValueError('需要16kHz单声道PCM音频')
        return np.frombuffer(audio.readframes(audio.getnframes()),dtype=np.int16).astype(np.float32)/32768

def write_wav(path,samples):
    target=Path(path);temp=target.with_suffix('.partial.wav')
    pcm=np.round(np.clip(samples,-1,1)*32767).astype('<i2')
    with wave.open(str(temp),'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(pcm.tobytes())
    temp.replace(target)

class AudioModels:
    def __init__(self,root):
        self.root=Path(root);self.denoiser=None;self.diarizer=None
        self.noise_lock=threading.Lock();self.speaker_lock=threading.Lock()

    def enhance(self,samples,prefix=None):
        import sherpa_onnx as s
        original=np.ascontiguousarray(samples,dtype=np.float32)
        if not len(original):return original.copy()
        context=np.asarray(prefix,dtype=np.float32)[-8000:] if prefix is not None else np.empty(0,dtype=np.float32)
        padded=np.concatenate((context,original,np.zeros(512,dtype=np.float32)))
        with self.noise_lock:
            if self.denoiser is None:
                config=s.OfflineSpeechDenoiserConfig(model=s.OfflineSpeechDenoiserModelConfig(gtcrn=s.OfflineSpeechDenoiserGtcrnModelConfig(model=str(self.root/'gtcrn.onnx')),num_threads=1,provider='cpu'))
                if not config.validate():raise RuntimeError('降噪模型未就绪')
                self.denoiser=s.OfflineSpeechDenoiser(config)
            result=self.denoiser(padded,16000)
            if result.sample_rate!=16000:raise RuntimeError('降噪输出采样率异常')
            clean=np.asarray(result.samples,dtype=np.float32)[len(context):len(context)+len(original)]
        if len(clean)!=len(original) or not np.isfinite(clean).all():raise RuntimeError('降噪输出不完整')
        return np.ascontiguousarray(clean)

    def enhance_file(self,source,target,checkpoint=lambda:None):
        target=Path(target);temp=target.with_suffix('.partial.wav');prefix=None
        try:
            with wave.open(str(source),'rb') as audio,wave.open(str(temp),'wb') as output:
                if (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())!=(16000,1,2):raise ValueError('音频格式不符')
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000)
                while raw:=audio.readframes(64000):
                    checkpoint();samples=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768
                    clean=self.enhance(samples,prefix);prefix=samples[-8000:]
                    output.writeframes(np.round(np.clip(clean,-1,1)*32767).astype('<i2').tobytes())
            temp.replace(target)
        except Exception:
            temp.unlink(missing_ok=True);raise

    def diarize(self,samples,checkpoint=lambda:None):
        import sherpa_onnx as s
        samples=np.ascontiguousarray(samples,dtype=np.float32)
        if not len(samples):return []
        checkpoint()
        with self.speaker_lock:
            if self.diarizer is None:
                config=s.OfflineSpeakerDiarizationConfig(
                    segmentation=s.OfflineSpeakerSegmentationModelConfig(pyannote=s.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(self.root/'speaker-segmentation.onnx'),window_shift_ratio=0.1),num_threads=1,provider='cpu'),
                    embedding=s.SpeakerEmbeddingExtractorConfig(model=str(self.root/'speaker-embedding.onnx'),num_threads=1,provider='cpu'),
                    clustering=s.FastClusteringConfig(num_clusters=-1,threshold=0.9),min_duration_on=0.3,min_duration_off=0.5)
                if not config.validate():raise RuntimeError('发言人模型未就绪')
                self.diarizer=s.OfflineSpeakerDiarization(config)
            def progress(done,total):checkpoint();return 0
            result=self.diarizer.process(samples,callback=progress).sort_by_start_time()
        mapping={};turns=[];duration=len(samples)/16000
        for turn in result:
            if turn.speaker<0:continue
            start=max(0,float(turn.start));end=min(duration,float(turn.end))
            if end<=start:continue
            if turn.speaker not in mapping:mapping[turn.speaker]=len(mapping)+1
            turns.append({'start':round(start,3),'end':round(end,3),'speaker_id':mapping[turn.speaker],'speaker':'发言人 '+str(mapping[turn.speaker])})
        return turns

@lru_cache(maxsize=2)
def models_for(data):return AudioModels(Path(data)/'models'/'audio')

def label_segments(segments,turns):
    """Keep recognized words; align to turns without inventing separate audio tracks."""
    turns=sorted(turns,key=lambda t:t['start']);starts=[t['start'] for t in turns];cursor=0
    def identify(start,end):
        nonlocal cursor
        while cursor<len(turns) and turns[cursor]['end']<=start:cursor+=1
        scores={};duration=max(.02,end-start)
        for index in range(cursor,bisect.bisect_left(starts,end)):
            turn=turns[index]
            overlap=max(0,min(end,turn['end'])-max(start,turn['start']))
            if overlap:scores[turn['speaker_id']]=scores.get(turn['speaker_id'],0)+overlap
        ranked=sorted(scores,key=scores.get,reverse=True)
        if not ranked or scores[ranked[0]]<min(.03,duration*.2):return {'speaker':'未确定','speaker_uncertain':True}
        # Overlap is marked, never presented as cleanly isolated voices.
        if len(ranked)>1 and scores[ranked[1]]>=duration*.4:
            return {'speaker':'多人重叠','speaker_ids':sorted(ranked[:2]),'speaker_uncertain':True}
        return {'speaker_id':ranked[0],'speaker':'发言人 '+str(ranked[0])}
    labeled=[]
    for segment in segments:
        words=segment.get('words') or [{'start':segment['start'],'end':segment['end'],'word':segment['text']}]
        for word in words:
            text=word.get('word',word.get('text',''))
            if not text.strip():continue
            item={'start':word['start'],'end':word['end'],'text':text,**identify(word['start'],word['end'])}
            previous=labeled[-1] if labeled else None
            if previous and previous['speaker']==item['speaker'] and previous.get('speaker_ids')==item.get('speaker_ids') and item['start']-previous['end']<1.2 and item['end']-previous['start']<25 and len(previous['text'])+len(text)<220:
                separator=' ' if previous['text'][-1:].isascii() and previous['text'][-1:].isalnum() and text[:1].isascii() and text[:1].isalnum() else ''
                previous['text']+=separator+text;previous['end']=item['end']
            else:labeled.append(item)
    for item in labeled:item['text']=item['text'].strip()
    return labeled
