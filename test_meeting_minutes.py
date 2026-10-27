import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app

class MeetingSummaryTests(unittest.TestCase):
    def test_short_and_long_recordings_use_free_summary(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DATA',Path(tmp)):
            c=TestClient(app.app)
            for size in (100,8000):
                r=app.new('录音测试','meeting');r.update(status='done',text='今天反思'*size,summary_status='none',diarization_status='done');app.save(r)
                seen=[]
                def generate(model,context,prompt,*args,**kwargs):
                    seen.append((prompt,kwargs))
                    return '今天重新想清楚了工作安排，也留意到了自己的感受。'
                with patch.object(app,'generate',side_effect=generate):
                    response=c.post('/api/jobs/'+r['id']+'/chat',json={'summary':True,'model':'local'})
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(all(not kw.get('format_schema') for _,kw in seen))
                self.assertIn('不套固定模板',seen[-1][0])
                self.assertFalse(any('不加入反思' in prompt for prompt,_ in seen))
                self.assertEqual(app.read(r['id'])['summary'],'今天重新想清楚了工作安排，也留意到了自己的感受。')

if __name__=='__main__':unittest.main()
