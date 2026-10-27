import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from fastapi.testclient import TestClient
import app
from live_speakers import LiveSpeakers

class LiveSpeakerTests(unittest.TestCase):
    def test_identity_is_stable_per_record_and_uncertain_is_not_forced(self):
        live=LiveSpeakers('unused');x=np.array([1.,0.,0.]);y=np.array([0.,1.,0.])
        self.assertEqual(live.match('one',x),1);self.assertEqual(live.match('one',x),1)
        self.assertEqual(live.match('one',y),2);self.assertEqual(live.match('two',y),1)
        unsure=np.array([.5,.5,np.sqrt(.5)]);self.assertIsNone(live.match('one',unsure))
        live.clear('one');self.assertNotIn('one',live.sessions)
    def test_short_speech_gets_unknown_not_a_fake_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for f in ('speaker-segmentation.onnx','speaker-embedding.onnx'):(root/f).touch()
            live=LiveSpeakers(root)
            live.analysis=SimpleNamespace(diarize=lambda x:[{'start':0,'end':.2,'speaker_id':1}])
            labeled,count=live.process('one',np.ones(16000),[{'start':0,'end':1,'text':'短句'}],0)
            self.assertEqual(count,0);self.assertEqual(labeled[0]['speaker'],'未确定');self.assertTrue(labeled[0]['speaker_provisional'])

class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.temp.name);self.c=TestClient(app.app)
    def tearDown(self):app.DATA=self.old;self.temp.cleanup()
    def record(self,**extra):
        r=app.new('删除测试','meeting');r.update(status='done',text='原文保留',summary='结论保留',recording_chunks=[{'state':'done'}],diarization_status='done',summary_status='done',**extra);app.save(r)
        root=app.DATA/r['id'];(root/'chunks').mkdir();(root/'chunks/00000.wav').write_bytes(b'raw');(root/'source.wav').write_bytes(b'raw');(root/'enhanced.wav').write_bytes(b'clean');(root/'audio.wav').write_bytes(b'converted')
        return r
    def test_audio_only_removes_all_audio_and_keeps_text(self):
        r=self.record();id=r['id'];response=self.c.delete('/api/meetings/'+id+'?audio_only=true');self.assertEqual(response.status_code,200,response.text)
        result=self.c.get('/api/jobs/'+id).json();self.assertEqual(result['text'],'原文保留');self.assertEqual(result['summary'],'结论保留');self.assertTrue(result['audio_deleted']);self.assertFalse(result['media_url']);self.assertFalse(result['enhanced_url'])
        self.assertFalse((app.DATA/id/'chunks').exists());self.assertFalse(list((app.DATA/id).glob('*.wav')))
        self.assertEqual(self.c.get('/api/jobs/'+id+'/media').status_code,404)
        self.assertEqual(self.c.post('/api/meetings/'+id+'/retry').status_code,409)
        self.assertEqual(self.c.delete('/api/meetings/'+id+'?audio_only=true').status_code,200)
    def test_entire_record_removed_from_resources_and_history(self):
        r=self.record();id=r['id'];self.assertEqual(self.c.delete('/api/meetings/'+id).status_code,200)
        self.assertEqual(self.c.get('/api/jobs/'+id).status_code,404);self.assertEqual(self.c.get('/api/meetings').json(),[]);self.assertEqual(self.c.get('/api/jobs').json(),[])
        self.assertFalse((app.DATA/id).exists());self.assertEqual(list((app.DATA/'.deleting').iterdir()),[])
    def test_active_or_background_processing_rejected(self):
        r=self.record()
        for fields in ({'status':'recording'},{'status':'done','summary_status':'running'},{'summary_status':'done','diarization_status':'running'}):
            r.update(fields);app.save(r)
            self.assertEqual(self.c.delete('/api/meetings/'+r['id']).status_code,409)
            self.assertTrue((app.DATA/r['id']/'source.wav').exists())
    def test_non_recording_cannot_be_deleted(self):
        r=app.new('video','upload');self.assertEqual(self.c.delete('/api/meetings/'+r['id']).status_code,404);self.assertTrue((app.DATA/r['id']).exists())
    def test_question_in_progress_cannot_delete_recording(self):
        r=self.record()
        def generate(*args):
            self.assertEqual(self.c.delete('/api/meetings/'+r['id']).status_code,409)
            return '回答'
        with patch.object(app,'generate',side_effect=generate):
            response=self.c.post('/api/jobs/'+r['id']+'/chat',json={'model':'local','question':'说了什么'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(app.active_chats,{})
        self.assertEqual(self.c.delete('/api/meetings/'+r['id']).status_code,200)

    def test_audio_save_failure_restores_files(self):
        r=self.record();original=app.save
        def save(value):
            if value.get('audio_deleted'):raise OSError('disk failure')
            return original(value)
        with patch.object(app,'save',side_effect=save):
            c=TestClient(app.app,raise_server_exceptions=False)
            self.assertEqual(c.delete('/api/meetings/'+r['id']+'?audio_only=true').status_code,500)
        self.assertTrue((app.DATA/r['id']/'source.wav').exists());self.assertTrue((app.DATA/r['id']/'chunks/00000.wav').exists());self.assertFalse(app.read(r['id']).get('audio_deleted'))

if __name__=='__main__':unittest.main()
