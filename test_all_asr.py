import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
import app

class UnifiedASRTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name)
        root=app.DATA/'models'/'sensevoice';root.mkdir(parents=True)
        for name in ('tokens.txt','model.int8.onnx'):(root/name).write_bytes(b'test')
        self.c=TestClient(app.app)
    def tearDown(self):app.DATA=self.old;self.tmp.cleanup()
    def test_media_inputs_default_to_sensevoice_and_reject_old_models(self):
        with patch.object(app.pool,'submit') as submit:
            r=self.c.post('/api/import',json={'url':'https://www.bilibili.com/video/BVtest/'})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(submit.call_args.args[-2],'sensevoice')
            r=self.c.post('/api/upload',files={'file':('video.mp4',b'video')})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(submit.call_args.args[-2],'sensevoice')
            for model in ('base','small','medium'):
                self.assertEqual(self.c.post('/api/import',json={'url':'https://www.bilibili.com/video/BVtest/','model':model}).status_code,400)
                self.assertEqual(self.c.post('/api/upload',data={'model':model},files={'file':('x.wav',b'x')}).status_code,400)
    def test_live_and_video_reuse_single_instance(self):
        model=object()
        with patch.dict(app.recording_models,{},clear=True),patch('sensevoice_asr.SenseVoiceModel',return_value=model) as build:
            with app.recording_model_lock:first=app.shared_asr()
            with app.recording_model_lock:second=app.shared_asr()
            self.assertIs(first,second);self.assertIs(first,model);self.assertEqual(build.call_count,1)
    def test_video_reads_bounded_windows_and_records_new_model(self):
        rec=app.new('视频','upload');root=app.DATA/rec['id']
        with wave.open(str(root/'audio.wav'),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*(31*16000))
        lengths=[]
        def decode(samples):
            lengths.append(len(samples));return ([SimpleNamespace(start=0,end=min(1,len(samples)/16000),text='文字',words=[])],None)
        fake=SimpleNamespace(transcribe=decode)
        with patch.dict(app.recording_models,{'sensevoice':fake},clear=True),patch.object(app.subprocess,'run'),patch.object(app,'ensure_cover'):
            app.transcribe(rec,root/'source.wav','base') # old queued jobs must also use SenseVoice
        self.assertEqual(lengths,[15*16000,15*16000,16000])
        self.assertEqual([s['start'] for s in rec['segments']],[0,15,30])
        self.assertEqual(rec['duration'],31);self.assertEqual(rec['asr_model'],'sensevoice')

if __name__=='__main__':unittest.main()
