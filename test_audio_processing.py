import io
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from fastapi.testclient import TestClient
import app
import audio_processing as audio
from recording_priority import RecordingPriority

class AlignmentTests(unittest.TestCase):
    def test_word_timestamps_split_speakers_without_losing_text(self):
        segments=[{'start':0,'end':2,'text':'你好再见','words':[{'start':0,'end':1,'word':'你好'},{'start':1,'end':2,'word':'再见'}]}]
        turns=[{'start':0,'end':1,'speaker_id':1},{'start':1,'end':2,'speaker_id':2}]
        result=audio.label_segments(segments,turns)
        self.assertEqual([r['speaker'] for r in result],['发言人 1','发言人 2'])
        self.assertEqual(''.join(r['text'] for r in result),'你好再见')
    def test_overlap_and_missing_voice_are_not_fabricated_speakers(self):
        result=audio.label_segments([{'start':0,'end':1,'text':'同时发言'}],[{'start':0,'end':1,'speaker_id':1},{'start':0,'end':1,'speaker_id':2}])
        self.assertEqual(result[0]['speaker'],'多人重叠');self.assertTrue(result[0]['speaker_uncertain'])
        result=audio.label_segments([{'start':2,'end':3,'text':'不确定'}],[])
        self.assertEqual(result[0]['speaker'],'未确定');self.assertNotIn('speaker_id',result[0])
    def test_fallback_segments_preserve_english_word_boundaries(self):
        result=audio.label_segments([{'start':0,'end':1,'text':'Hello'},{'start':1,'end':2,'text':'world'}],[{'start':0,'end':2,'speaker_id':1}])
        self.assertEqual(result[0]['text'],'Hello world')
    def test_missing_or_modified_models_are_not_reported_as_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'models'/'audio';root.mkdir(parents=True)
            for name in audio.ASSETS:(root/name).write_bytes(b'not a model')
            status=audio.model_status(tmp)
        self.assertFalse(status['denoise_available']);self.assertFalse(status['diarization_available'])

class AudioPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name)
        (app.DATA/'models'/'sensevoice').mkdir(parents=True)
        for name in ('model.int8.onnx','tokens.txt'):(app.DATA/'models'/'sensevoice'/name).write_bytes(b'test model')
        self.client=TestClient(app.app)
        self.patches=[patch.object(app.recording_pool,'submit'),patch.object(app.pool,'submit'),patch.object(app,'recording_priority',RecordingPriority()),patch.object(audio,'model_status',return_value={'denoise_available':True,'diarization_available':True,'diarization_model':'test speakers'})]
        self.recording,self.background,*_= [p.start() for p in self.patches]
        self.service=SimpleNamespace(enhance=lambda x,prefix:x*.5,diarize=lambda x,checkpoint:[{'start':0,'end':.5,'speaker_id':1,'speaker':'发言人 1'},{'start':.5,'end':1,'speaker_id':2,'speaker':'发言人 2'}])
        self.input=None
        def transcribe(x,**kwargs):
            self.input=x.copy()
            return ([SimpleNamespace(start=0,end=1,text='你好再见',words=[SimpleNamespace(start=0,end=.5,word='你好'),SimpleNamespace(start=.5,end=1,word='再见')])],None)
        self.model_patch=patch.dict(app.recording_models,{'sensevoice':SimpleNamespace(transcribe=transcribe)},clear=True);self.model_patch.start()
        self.service_patch=patch.object(audio,'models_for',return_value=self.service);self.service_patch.start()
        self.raw=io.BytesIO()
        with wave.open(self.raw,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(np.full(16000,8000,dtype='<i2').tobytes())
    def tearDown(self):
        self.service_patch.stop();self.model_patch.stop()
        for p in reversed(self.patches):p.stop()
        app.DATA=self.old;self.tmp.cleanup()
    def start_and_chunk(self):
        jid=self.client.post('/api/meetings',json={}).json()['id']
        response=self.client.post('/api/meetings/'+jid+'/chunks',data={'sequence':0},files={'file':('chunk.wav',self.raw.getvalue())})
        self.assertEqual(response.status_code,200)
        fn,*args=self.recording.call_args.args;fn(*args)
        return jid
    def finish(self,jid):
        self.client.post('/api/meetings/'+jid+'/finish',json={'chunks':1})
        fn,*args=self.recording.call_args.args;fn(*args)
        fn,*args=self.background.call_args.args;fn(*args)
    def test_denoise_asr_speakers_export_and_original_are_connected(self):
        jid=self.start_and_chunk();self.finish(jid);r=app.read(jid)
        np.testing.assert_allclose(self.input,8000/32768*.5)
        self.assertEqual(r['noise_suppression_status'],'done');self.assertEqual(r['diarization_status'],'done');self.assertEqual(r['speaker_count'],2)
        self.assertEqual([s['speaker'] for s in r['segments']],['发言人 1','发言人 2'])
        self.assertEqual((app.DATA/jid/'source.wav').read_bytes(),self.raw.getvalue())
        detail=self.client.get('/api/jobs/'+jid).json();self.assertTrue(detail['enhanced_url'])
        self.assertEqual(self.client.get(detail['enhanced_url']).status_code,200)
        self.assertIn('发言人 1',self.client.get('/api/jobs/'+jid+'/export').text)
    def test_noise_failure_falls_back_to_original(self):
        def fail(*args):raise RuntimeError('unavailable')
        self.service.enhance=fail;jid=self.start_and_chunk();self.finish(jid);r=app.read(jid)
        np.testing.assert_allclose(self.input,8000/32768)
        self.assertEqual(r['noise_suppression_status'],'fallback');self.assertEqual(r['status'],'done');self.assertTrue(r['text'])
        self.assertEqual((app.DATA/jid/'source.wav').read_bytes(),self.raw.getvalue())
    def test_diarization_failure_preserves_transcript(self):
        def fail(*args):raise RuntimeError('unavailable')
        self.service.diarize=fail;jid=self.start_and_chunk();self.finish(jid);r=app.read(jid)
        self.assertEqual(r['diarization_status'],'error');self.assertEqual(r['text'],'你好再见');self.assertEqual(r['status'],'done')
    def test_background_save_keeps_newer_user_title_and_project(self):
        jid=self.start_and_chunk();stale=app.read(jid)
        self.client.patch('/api/meetings/'+jid,json={'title':'用户改的新标题'})
        stale['message']='进度更新';app.save(stale)
        self.assertEqual(app.read(jid)['title'],'用户改的新标题')
    def test_retry_options_can_disable_models(self):
        jid=self.start_and_chunk();self.finish(jid)
        response=self.client.post('/api/meetings/'+jid+'/retry',json={'denoise':False,'diarization':False})
        self.assertEqual(response.status_code,200)
        r=app.read(jid);self.assertEqual(r['noise_suppression_status'],'off');self.assertEqual(r['diarization_status'],'off')
    def test_new_recording_pauses_postprocessing(self):
        jid=self.start_and_chunk()
        self.client.post('/api/meetings/'+jid+'/finish',json={'chunks':1});fn,*args=self.recording.call_args.args;fn(*args)
        self.assertEqual(app.read(jid)['diarization_status'],'queued')
        self.assertIsNot(self.recording,self.background)

if __name__=='__main__':unittest.main()
