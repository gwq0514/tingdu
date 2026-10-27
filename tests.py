import unittest, tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=app.DATA; app.DATA=Path(self.tmp.name)
        model=app.DATA/'models'/'sensevoice';model.mkdir(parents=True)
        for name in ('model.int8.onnx','tokens.txt'):(model/name).write_bytes(b'test model')
        self.client=TestClient(app.app)
    def tearDown(self): app.DATA=self.old; self.tmp.cleanup()
    def test_text_roundtrip_export(self):
        r=self.client.post('/api/import',json={'text':'这是正文。第二句。','title':'文章'})
        self.assertEqual(r.status_code,200); jid=r.json()['id']
        self.assertEqual(self.client.get('/api/jobs/'+jid).json()['text'],'这是正文。第二句。')
        self.assertIn('这是正文',self.client.get('/api/jobs/'+jid+'/export').text)
    def test_block_remote_origin_and_bad_url(self):
        self.assertEqual(self.client.post('/api/import',headers={'Origin':'https://evil.example'},json={'text':'x'}).status_code,403)
        self.assertEqual(self.client.post('/api/import',json={'url':'http://127.0.0.1:22'}).status_code,400)
        self.assertEqual(self.client.get('/api/jobs/invalid').status_code,404)
    def test_share_url_keeps_parameters(self):
        with patch.object(app.pool,'submit') as submit:
            r=self.client.post('/api/import',json={'url':'分享 http://xhslink.com/abc?foo=bar 更多文字'})
            self.assertEqual(r.status_code,200)
            self.assertEqual(submit.call_args.args[2],'http://xhslink.com/abc?foo=bar')
    def test_upload_rejects_non_media(self):
        self.assertEqual(self.client.post('/api/upload',files={'file':('a.exe',b'x')}).status_code,400)

    def test_library_metadata_and_local_storage_location(self):
        r=self.client.post('/api/import',json={'text':'内容','title':'资源标题'}).json()
        detail=self.client.get('/api/jobs/'+r['id']).json()
        self.assertEqual(detail['local_path'],str((app.DATA/r['id']).resolve()))
        self.assertIn('created_at',self.client.get('/api/jobs').json()[0])
        storage=self.client.get('/api/storage').json()
        self.assertFalse(storage['remote_upload'])
        self.assertFalse(storage['public_ready'])

    def test_media_cannot_escape_resource_directory(self):
        r=app.new('恶意路径','upload')
        outside=app.DATA/'private.wav'; outside.write_bytes(b'private')
        r['media_file']='../private.wav'; app.save(r)
        self.assertEqual(self.client.get('/api/jobs/'+r['id']+'/media').status_code,404)

    def test_local_media_and_cover_are_readable(self):
        r=app.new('视频','upload'); root=app.DATA/r['id']
        (root/'source.mp4').write_bytes(b'video')
        (root/'cover.jpg').write_bytes(b'image')
        detail=self.client.get('/api/jobs/'+r['id']).json()
        self.assertEqual(detail['media_file'],'source.mp4')
        self.assertTrue(detail['cover_url'].endswith('/cover'))
        self.assertEqual(self.client.get(detail['media_url']).content,b'video')
        self.assertEqual(self.client.get(detail['cover_url']).content,b'image')
    def test_long_summary_processes_every_section(self):
        r=self.client.post('/api/import',json={'text':'中文'*10000})
        with patch('app.generate',return_value='分段摘要') as generate:
            response=self.client.post('/api/jobs/'+r.json()['id']+'/chat',json={'summary':True,'model':'local'})
            self.assertEqual(response.status_code,200)
            supplied=''.join(call.args[1] for call in generate.call_args_list[:-1])
            self.assertEqual(supplied.replace('\n',''),'中文'*10000)
    def test_generation_uses_local_model(self):
        r=self.client.post('/api/import',json={'text':'今天学习了两种方法。'})
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'message':{'content':'两种方法'}}
        with patch('app.httpx.post',return_value=Response()) as send:
            result=self.client.post('/api/jobs/'+r.json()['id']+'/chat',json={'summary':True,'model':'local'})
            self.assertEqual(result.json()['answer'],'两种方法')
            self.assertTrue(send.call_args.args[0].startswith('http://127.0.0.1:11434/'))

    def test_simplified_query_retrieves_traditional_evidence(self):
        r=self.client.post('/api/import',json={'text':'无关文字'*2000+'備忘功能互動能力比較弱。'})
        with patch('app.generate',return_value='互动能力弱') as generate:
            response=self.client.post('/api/jobs/'+r.json()['id']+'/chat',json={'question':'备忘功能有什么评价？','model':'local'})
            self.assertEqual(response.status_code,200)
            self.assertIn('備忘功能',generate.call_args.args[1])

if __name__=='__main__': unittest.main()
