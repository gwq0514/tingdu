import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from recording_priority import RecordingPriority

class PriorityTests(unittest.TestCase):
    def test_pending_audio_stays_priority_after_capture_stops(self):
        gate=RecordingPriority();gate.start('recording');gate.enqueue('recording');gate.enqueue('recording')
        gate.stop('recording');self.assertTrue(gate.busy())
        gate.completed('recording');self.assertTrue(gate.busy())
        gate.completed('recording');self.assertFalse(gate.busy())

    def test_live_queue_runs_while_background_waits(self):
        gate=RecordingPriority();gate.start('live');gate.enqueue('live')
        entered=threading.Event();resumed=threading.Event();order=[]
        def background():
            entered.set();gate.wait_for_background();order.append('video');resumed.set()
        def live():
            order.append('recording');gate.completed('live');gate.stop('live')
        with ThreadPoolExecutor(max_workers=1) as videos,ThreadPoolExecutor(max_workers=1) as recordings:
            video=videos.submit(background);self.assertTrue(entered.wait(1));self.assertFalse(resumed.is_set())
            recordings.submit(live).result(timeout=2);video.result(timeout=2)
        self.assertEqual(order,['recording','video'])

    def test_closed_page_lease_expires_but_received_audio_does_not(self):
        now=[0.0];gate=RecordingPriority(lease_seconds=20,clock=lambda:now[0])
        gate.start('closed');now[0]=21;self.assertFalse(gate.busy())
        gate.enqueue('received');now[0]=100;self.assertTrue(gate.busy())
        gate.completed('received');self.assertFalse(gate.busy())

    def test_waits_for_all_recordings_not_only_first(self):
        gate=RecordingPriority();gate.start('a');gate.start('b');gate.stop('a');self.assertTrue(gate.busy());gate.stop('b');self.assertFalse(gate.busy())

    def test_video_yields_between_decoder_segments(self):
        import tempfile,wave
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        import app
        gate=RecordingPriority();waiting=threading.Event();release=threading.Event();finished=threading.Event();order=[]
        calls=[0]
        def transcribe(*args,**kwargs):
            calls[0]+=1
            if calls[0]==1:gate.start('live');waiting.set()
            if calls[0]==3:order.append('third-decoder-step')
            return ([SimpleNamespace(start=0,end=1,text='一句文字')],None)
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DATA',Path(tmp)),patch.object(app,'recording_priority',gate):
            rec=app.new('视频','upload');root=app.DATA/rec['id']
            with wave.open(str(root/'audio.wav'),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\0\0'*(45*16000))
            fake=SimpleNamespace(transcribe=transcribe)
            original=gate.wait_for_background
            def observe():
                if gate.busy():release.set()
                original()
            with patch.dict(app.recording_models,{'sensevoice':fake},clear=True),patch.object(app,'require_asr'),patch.object(app.subprocess,'run'),patch.object(app,'ensure_cover'),patch.object(gate,'wait_for_background',side_effect=observe):
                def worker():
                    try:app.transcribe(rec,root/'source.wav','sensevoice')
                    finally:finished.set()
                thread=threading.Thread(target=worker);thread.start()
                try:
                    self.assertTrue(waiting.wait(2));self.assertTrue(release.wait(2));self.assertNotIn('third-decoder-step',order)
                    self.assertTrue(app.recording_model_lock.acquire(blocking=False))
                    app.recording_model_lock.release()
                finally:
                    gate.stop('live');thread.join(timeout=2)
                self.assertTrue(finished.is_set());self.assertEqual(len(rec['segments']),3)

if __name__=='__main__':unittest.main()
