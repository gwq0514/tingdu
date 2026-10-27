import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app


def wav(seconds=1, rate=16000):
    data=io.BytesIO()
    with wave.open(data,'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate);out.writeframes(b'\0\0'*int(seconds*rate))
    return data.getvalue()

class MeetingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name)
        (app.DATA/'models'/'sensevoice').mkdir(parents=True)
        for name in ('model.int8.onnx','tokens.txt'):(app.DATA/'models'/'sensevoice'/name).write_bytes(b'test model')
        self.client=TestClient(app.app)
        self.pool=patch.object(app.recording_pool,'submit');self.submit=self.pool.start()
        self.background=patch.object(app.pool,'submit');self.background_submit=self.background.start()
        from recording_priority import RecordingPriority
        self.priority_patch=patch.object(app,'recording_priority',RecordingPriority());self.priority_patch.start()
    def tearDown(self):
        self.priority_patch.stop();self.background.stop();self.pool.stop();app.DATA=self.old;self.tmp.cleanup()
    def start(self,**kwargs):
        response=self.client.post('/api/meetings',json=kwargs)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['id']
    def chunk(self,jid,n=0,data=None):
        return self.client.post('/api/meetings/'+jid+'/chunks',data={'sequence':n},files={'file':('chunk.wav',wav() if data is None else data,'audio/wav')})
    def finish(self,jid,count):
        return self.client.post('/api/meetings/'+jid+'/finish',json={'chunks':count})
    def test_independent_page_and_shared_history(self):
        jid=self.start(title='规划会议')
        self.assertEqual(self.client.get('/meetings').status_code,200)
        self.assertEqual(self.client.get('/api/meetings').json()[0]['id'],jid)
        self.assertEqual(self.client.get('/api/jobs').json()[0]['source'],'meeting')
    def test_validate_model_audio_and_sequence(self):
        self.assertEqual(self.client.post('/api/meetings',json={'model':'medium'}).status_code,400)
        self.assertEqual(self.client.post('/api/meetings',json={'model':'small'}).status_code,400)
        jid=self.start()
        self.assertEqual(self.chunk(jid,1).status_code,409)
        self.assertEqual(self.chunk(jid,data=b'bad').status_code,400)
        self.assertEqual(self.chunk(jid,data=wav(rate=8000)).status_code,400)
        self.assertEqual(self.finish(jid,1).status_code,409)
        self.assertEqual(len(app.read(jid)['recording_chunks']),0)
    def test_upload_is_idempotent_and_conflict_safe(self):
        jid=self.start();self.assertEqual(self.chunk(jid).status_code,200)
        self.assertTrue(self.chunk(jid).json()['duplicate'])
        self.assertEqual(self.chunk(jid,data=wav(.5)).status_code,409)
        self.assertEqual(len(app.read(jid)['recording_chunks']),1)
        self.assertEqual(self.submit.call_count,1)
    def test_finish_preserves_pcm_and_does_not_queue_twice(self):
        jid=self.start();self.chunk(jid);self.chunk(jid,1,data=wav(.5))
        self.assertEqual(self.finish(jid,2).status_code,200)
        fn,*args=self.submit.call_args.args;fn(*args)
        record=app.read(jid)
        self.assertEqual(record['status'],'done')
        self.assertEqual(record['duration'],1.5)
        with wave.open(str(app.DATA/jid/'source.wav'),'rb') as audio:self.assertEqual(audio.getnframes(),24000)
        before=self.submit.call_count;self.finish(jid,2);self.assertEqual(self.submit.call_count,before)
        self.assertEqual(self.chunk(jid,2).status_code,409)
        self.assertTrue(self.chunk(jid).json()['duplicate'])
        self.assertEqual(self.client.get('/api/jobs/'+jid+'/media').status_code,200)
    def test_chunk_timestamps_are_offset_and_text_is_preserved(self):
        from types import SimpleNamespace
        jid=self.start();self.chunk(jid);self.chunk(jid,1)
        fn,*args=self.submit.call_args.args
        fake=SimpleNamespace(transcribe=lambda *a,**k:([SimpleNamespace(start=.1,end=.5,text='我们确定先测试。')],None))
        with patch.dict(app.recording_models,{'sensevoice':fake},clear=True):fn(*args)
        r=app.read(jid)
        self.assertEqual(r['segments'][0]['start'],1.1)
        self.assertEqual(r['transcribed_chunks'],1)
        self.assertIn('先测试',r['text'])
    def test_failed_asr_keeps_audio_and_reports_gap(self):
        jid=self.start();self.chunk(jid);fn,*args=self.submit.call_args.args
        with patch.dict(app.recording_models,{'sensevoice':object()},clear=True):fn(*args)
        self.finish(jid,1);fn,*args=self.submit.call_args.args;fn(*args)
        r=app.read(jid);self.assertEqual(r['failed_chunks'],1);self.assertEqual(r['status'],'done')
        self.assertTrue((app.DATA/jid/'source.wav').exists());self.assertIn('部分片段',r['message'])
    def test_summary_failure_keeps_recording_and_transcript(self):
        jid=self.start();self.chunk(jid);r=app.read(jid)
        r['llm_model']='local';r['recording_chunks'][0].update(state='done',segments=[{'start':0,'end':1,'text':'明天先完成测试。'}]);app.save(r);app.recording_priority.completed(jid)
        self.finish(jid,1);fn,*args=self.submit.call_args.args
        fn(*args)
        fn,*args=self.background_submit.call_args.args
        with patch.object(app,'chat',side_effect=RuntimeError('unavailable')):fn(*args)
        r=app.read(jid);self.assertEqual(r['summary_status'],'error');self.assertEqual(r['status'],'done');self.assertIn('完成测试',r['text']);self.assertTrue((app.DATA/jid/'source.wav').exists())
    def test_restart_recovers_received_audio(self):
        jid=self.start();self.chunk(jid)
        for callback in app.app.router.on_startup:callback()
        self.assertEqual(app.read(jid)['status'],'error')
        self.assertTrue((app.DATA/jid/'source.wav').exists())
        self.assertEqual(self.client.post('/api/meetings/'+jid+'/retry').status_code,200)
    def test_rename_and_guard_non_meeting(self):
        jid=self.start();self.assertEqual(self.client.patch('/api/meetings/'+jid,json={'title':'复盘会议'}).status_code,200)
        self.assertEqual(app.read(jid)['title'],'复盘会议')
        self.assertEqual(self.client.patch('/api/meetings/'+jid,json={'title':'  '}).status_code,400)
        text=app.new('文章','text')
        self.assertEqual(self.client.post('/api/meetings/'+text['id']+'/finish',json={'chunks':0}).status_code,404)
        self.assertEqual(self.client.get('/api/meetings').json()[0]['title'],'复盘会议')
    def test_meeting_summary_does_not_invent_owners(self):
        jid=self.start();r=app.read(jid);r.update(status='done',text='先做测试。');app.save(r);app.recording_priority.stop(jid)
        with patch.object(app,'generate',return_value='{"meeting_summary":"先做测试","meeting_content":["测试"],"todos":[{"task":"测试","owner":"未明确","deadline":"未明确"}]}' ) as generate:
            response=self.client.post('/api/jobs/'+jid+'/chat',json={'summary':True,'model':'local'})
        self.assertEqual(response.status_code,200)
        self.assertIn('不编造事实',generate.call_args.args[2]);self.assertNotIn('format_schema',generate.call_args.kwargs)

    def test_projects_are_empty_until_user_creates_one(self):
        self.assertEqual(self.client.get('/api/recording-projects').json(),[])
        jid=self.start()
        self.assertEqual(app.read(jid)['project'],'')
        added=self.client.post('/api/recording-projects',json={'name':'我的思考'})
        self.assertEqual(added.json()['name'],'我的思考')
        self.client.post('/api/recording-projects',json={'name':' 我的思考 '})
        self.assertEqual(self.client.get('/api/recording-projects').json(),['我的思考'])
        self.assertEqual(self.client.patch('/api/meetings/'+jid,json={'project':'我的思考'}).status_code,200)
        self.assertEqual(app.read(jid)['project'],'我的思考')
        self.assertEqual(self.client.get('/api/meetings').json()[0]['project'],'我的思考')
        self.assertEqual(self.client.patch('/api/meetings/'+jid,json={'project':''}).status_code,200)
        self.assertEqual(app.read(jid)['project'],'')

    def test_project_validation_and_assignment_at_start(self):
        for name in ('', '../private', '项目/路径', '..', '未分类'):
            self.assertNotEqual(self.client.post('/api/recording-projects',json={'name':name}).status_code,200)
        self.assertEqual(self.client.post('/api/meetings',json={'project':'不存在'}).status_code,400)
        self.client.post('/api/recording-projects',json={'name':'新产品'})
        jid=self.start(project='新产品')
        self.assertEqual(app.read(jid)['project'],'新产品')
        self.assertEqual(self.client.patch('/api/meetings/'+jid,json={'project':'不存在'}).status_code,400)
        self.assertEqual(app.read(jid)['project'],'新产品')

if __name__=='__main__':unittest.main()
