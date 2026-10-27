import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from asr_vocabulary import Vocabulary,validate
from admin_vocabulary import create_app
from test_sensevoice import SenseVoiceTests
import numpy as np

class VocabularyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'admin'/'asr-vocabulary.json';self.v=Vocabulary(self.path)
    def tearDown(self):self.temp.cleanup()
    def save(self,entries,enabled=True):return self.v.save({'enabled':enabled,'entries':entries},self.v.read()['revision'])
    def test_reload_disabled_and_original_alignment(self):
        text='测试听堵工具';words=[SimpleNamespace(word=c,start=i*.1,end=(i+1)*.1) for i,c in enumerate(text)]
        self.assertEqual(self.v.apply(text,words)[0],text)
        self.save([{'term':'听读','aliases':['听堵']}])
        result,aligned,changes=self.v.apply(text,words)
        self.assertEqual(result,'测试听读工具');self.assertEqual(''.join(w.word for w in aligned),result)
        self.assertAlmostEqual(aligned[2].start,.2);self.assertAlmostEqual(aligned[2].end,.4)
        self.assertEqual(changes[0]['revision'],1)
        self.save([],False);self.assertEqual(self.v.apply(text,words)[0],text)
    def test_longest_single_pass_ascii_boundaries(self):
        self.save([{'term':'听读工具','aliases':['听堵工具']},{'term':'听读','aliases':['听堵']},{'term':'API','aliases':['api']}])
        output,_,changes=self.v.apply('听堵工具和听堵；api capital api2',[])
        self.assertEqual(output,'听读工具和听读；API capital api2');self.assertEqual(len(changes),3)
    def test_invalid_or_conflicting_rules_and_stale_save(self):
        for entries in ([{'term':'听读','aliases':['听']}],[{'term':'听读','aliases':['听堵']},{'term':'别词','aliases':['听堵']}],[{'term':'听读','aliases':['听堵']},{'term':'听堵','aliases':['别词']}]):
            with self.assertRaises(ValueError):self.save(entries)
        self.save([])
        with self.assertRaises(ValueError):self.v.save({'enabled':True,'entries':[]},0)
        self.assertEqual(os.stat(self.path).st_mode&0o777,0o600)
    def test_bad_manual_edit_keeps_raw_text(self):
        self.path.parent.mkdir();self.path.write_text('{broken')
        self.assertEqual(self.v.apply('原始识别',[]),('原始识别',[],[]))
    def test_real_adapter_hook_preserves_raw_and_updated_words(self):
        self.save([{'term':'听读','aliases':['听堵']}])
        model=SenseVoiceTests().model(SimpleNamespace(text='听堵',tokens=['听','堵'],timestamps=[.1,.4]));model.vocabulary=self.v
        segments,_=model.transcribe(np.ones(16000,dtype=np.float32)*.1)
        s=segments[0];self.assertEqual(s.text,'听读');self.assertEqual(s.raw_text,'听堵');self.assertEqual(''.join(w.word for w in s.words),s.text)
        self.assertEqual(len(s.text_corrections),1)

class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=create_app(self.root)
        self.c=TestClient(self.app,base_url='http://127.0.0.1:8767',client=('127.0.0.1',1234))
        self.token=(self.root/'admin'/'管理口令.txt').read_text().strip();self.auth={'Authorization':'Bearer '+self.token}
    def tearDown(self):self.temp.cleanup()
    def test_auth_origin_host_remote_and_no_secret_in_page(self):
        self.assertEqual(self.c.get('/api/vocabulary').status_code,401)
        self.assertEqual(self.c.get('/api/vocabulary',headers={'Authorization':'Bearer bad'}).status_code,401)
        self.assertNotIn(self.token,self.c.get('/').text)
        self.assertEqual(self.c.get('/api/vocabulary',headers={**self.auth,'Origin':'https://example.org'}).status_code,403)
        self.assertEqual(self.c.get('/',headers={'Host':'example.org'}).status_code,403)
        remote=TestClient(self.app,base_url='http://127.0.0.1:8767',client=('192.0.2.1',1234))
        self.assertEqual(remote.get('/',headers=self.auth).status_code,403)
        self.assertEqual(self.c.get('/openapi.json').status_code,404)
    def test_admin_not_available_from_content_server(self):
        import app
        c=TestClient(app.app)
        for path in ('/admin','/api/vocabulary','/admin.js','/static/vocabulary.js','/data/admin/管理口令.txt'):
            self.assertEqual(c.get(path).status_code,404,path)

    def test_save_preview_revision_and_disk_private(self):
        r=self.c.put('/api/vocabulary',headers=self.auth,json={'enabled':True,'revision':0,'entries':[{'term':'听读','aliases':['听堵']}]})
        self.assertEqual(r.status_code,200,r.text)
        preview=self.c.post('/api/preview',headers=self.auth,json={'text':'打开听堵'})
        self.assertEqual(preview.json()['text'],'打开听读')
        self.assertEqual(self.c.get('/api/vocabulary',headers=self.auth).json()['revision'],1)
        self.assertEqual(os.stat(self.root/'admin'/'管理口令.txt').st_mode&0o777,0o600)
        self.assertEqual(self.c.post('/api/preview',headers=self.auth,json={'text':'x'*5001}).status_code,400)
        self.assertEqual(self.c.put('/api/vocabulary',headers=self.auth,content=b'x'*512001).status_code,413)
        self.assertEqual(self.c.get('/api/vocabulary',headers=self.auth).headers['cache-control'],'no-store')

if __name__=='__main__':unittest.main()
