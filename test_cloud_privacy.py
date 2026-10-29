import importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

class CloudPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'TINGDU_PROFILE':'server-2gb','TINGDU_CLOUD_PRIVACY':'1','TINGDU_DATA_DIR':self.tmp.name,'TINGDU_ALLOWED_ORIGINS':'https://tingdu.online','TINGDU_LEGACY_CLAIM_TOKEN':'qa-only-secret'})
        self.env.start();spec=importlib.util.spec_from_file_location('cloud_test_engine',Path(__file__).with_name('app.py'));self.e=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.e;spec.loader.exec_module(self.e)
        self.a=TestClient(self.e.app,base_url='https://tingdu.online',headers={'host':'127.0.0.1:8768','origin':'https://tingdu.online'});self.b=TestClient(self.e.app,base_url='https://tingdu.online',headers={'host':'127.0.0.1:8768','origin':'https://tingdu.online'})
        self.a.get('/');self.b.get('/')
    def tearDown(self):self.e.low_runtime.close();self.env.stop();self.tmp.cleanup();sys.modules.pop('cloud_test_engine',None)
    def create(self):
        r=self.a.post('/api/import',json={'text':'Synthetic privacy fixture','title':'Private synthetic note'});self.assertEqual(r.status_code,200,r.text);return r.json()['id']
    def test_two_browser_capabilities_cannot_read_or_mutate_each_other(self):
        id=self.create();self.assertEqual(len(self.a.get('/api/jobs').json()),1);self.assertEqual(self.b.get('/api/jobs').json(),[])
        for path in ('','/media','/cover','/export','/creator'):
            self.assertEqual(self.b.get('/api/jobs/'+id+path).status_code,404,path)
        self.assertEqual(self.b.delete('/api/meetings/'+id).status_code,404)
        self.assertEqual(self.b.post('/api/subscriptions',json={'job_id':id}).status_code,404)
        self.assertTrue((self.e.DATA/id/'record.json').exists())
        record=self.a.get('/api/jobs/'+id).json();self.assertNotIn('local_path',record);self.assertNotIn('cloud_owner',record)
    def test_secure_cookie_csrf_and_forgery(self):
        r=self.a.get('/');cookie=r.headers['set-cookie'];self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=strict',cookie)
        self.assertEqual(self.a.post('/api/import',json={'text':'fixture'},headers={'origin':'https://other.example'}).status_code,403)
        c=TestClient(self.e.app,base_url='https://tingdu.online',headers={'host':'127.0.0.1:8768'});c.cookies.set('__Host-tingdu-session','f'*64+'.'+'0'*64)
        self.assertEqual(c.get('/api/jobs').status_code,401)
    def test_ack_removes_temporary_files_only_for_owner_after_completion(self):
        id=self.create();root=self.e.DATA/id;(root/'source.wav').write_bytes(b'fixture')
        self.assertEqual(self.b.post('/api/cloud/jobs/'+id+'/ack',json={'revision':0}).status_code,404)
        r=self.e.read(id);r['summary_status']='running';self.e.save(r)
        self.assertEqual(self.a.post('/api/cloud/jobs/'+id+'/ack',json={'revision':self.e.read(id).get('cloud_revision')}).status_code,409);self.assertTrue(root.exists())
        r['summary_status']='done';self.e.save(r)
        self.assertEqual(self.a.post('/api/cloud/jobs/'+id+'/ack',json={'revision':'stale'}).status_code,409);self.assertTrue(root.exists())
        self.assertEqual(self.a.post('/api/cloud/jobs/'+id+'/ack',json={'revision':self.e.read(id).get('cloud_revision')}).status_code,200);self.assertFalse(root.exists());self.assertEqual(self.a.get('/api/jobs').json(),[])
    def test_project_subscription_and_legacy_isolation(self):
        self.assertEqual(self.a.post('/api/recording-projects',json={'name':'QA category'}).status_code,200);self.assertEqual(self.b.get('/api/recording-projects').json(),[])
        r=self.a.post('/api/cloud/subscriptions/restore',json={'platform':'bilibili','id':'123','name':'QA author','url':'http://127.0.0.1/private'});self.assertEqual(r.status_code,200);self.assertTrue(r.json()['url'].startswith('https://space.bilibili.com/123'))
        self.assertEqual(self.b.get('/api/subscriptions').json(),[])
        old=self.e.new('Legacy synthetic fixture','text');old['status']='done';self.e.save(old)
        self.assertEqual(self.a.get('/api/jobs').json(),[])
        self.assertEqual(self.a.post('/api/cloud/claim-legacy',headers={'x-tingdu-legacy-owner':'verified'}).status_code,403)
        self.assertEqual(self.a.post('/api/cloud/claim-legacy',headers={'x-tingdu-legacy-owner':'qa-only-secret'}).status_code,200)
        self.assertEqual(len(self.a.get('/api/jobs').json()),1);self.assertEqual(self.b.get('/api/jobs').json(),[])
