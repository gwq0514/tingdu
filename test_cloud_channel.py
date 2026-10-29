import tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app
from meetings import recording_lock

class CloudChannelTests(unittest.TestCase):
    def test_cloud_assets_injected_only_in_cloud_responses(self):
        c=TestClient(app.app)
        for cloud in (False,True):
            with patch.object(app,'LOW_MEMORY',cloud):
                for url,name in (('/','index.html'),('/meetings?embedded=1','meetings.html')):
                    r=c.get(url)
                    self.assertEqual(r.status_code,200)
                    if cloud:
                        self.assertTrue(r.text.startswith('<!doctype html>'))
                        self.assertIn('/static/cloud-client.js?v=1.2.0-cloud.1',r.text)
                        self.assertEqual(r.headers['x-tingdu-channel'],'cloud')
                    else:
                        self.assertEqual(r.content,(app.ROOT/'static'/name).read_bytes())
                        self.assertNotIn('x-tingdu-channel',r.headers)
    def test_cloud_busy_record_lock_returns_promptly_and_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DATA',Path(tmp)),patch.object(app,'LOW_MEMORY',True):
            r=app.new('Synthetic lock test','meeting');r.update(status='done',summary_status='done',diarization_status='done');app.save(r)
            held=threading.Event();release=threading.Event()
            def hold():
                with recording_lock(r['id']):held.set();release.wait(8)
            t=threading.Thread(target=hold);t.start();held.wait(2)
            try:
                start=time.monotonic();response=TestClient(app.app).delete('/api/meetings/'+r['id'])
                self.assertEqual(response.status_code,409);self.assertLess(time.monotonic()-start,3)
                self.assertTrue((app.DATA/r['id']/'record.json').exists())
            finally:release.set();t.join()
