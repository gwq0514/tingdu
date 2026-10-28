import os,signal,tempfile,threading,time,unittest,multiprocessing as mp
from recording_priority import RecordingPriority
from inference_runtime import Runtime

def fake_worker(connection,phase,config):
    os.setsid();connection.send({'ready':True})
    while True:
        try:request=connection.recv()
        except EOFError:return
        p=request['payload']
        if p.get('crash'):os._exit(2)
        time.sleep(p.get('delay',0))
        connection.send({'ok':True,'result':{'pid':os.getpid(),'phase':phase,'value':p.get('value')}})

class ServerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.priority=RecordingPriority()
        self.runtime=Runtime(self.temp.name,self.priority,idle_seconds=.15,target=fake_worker)
    def tearDown(self):self.runtime.close();self.temp.cleanup()
    def wait(self,predicate,timeout=6):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.02)
        self.fail('state transition timed out')
    def test_audio_reuse_phase_reclamation_and_idle_unload(self):
        first=self.runtime.run('asr',{'value':'raw'})
        second=self.runtime.run('enhance',{'value':'clean'})
        self.assertEqual(first['pid'],second['pid'])
        llm=self.runtime.run('llm',{'value':'summary'})
        self.assertNotEqual(first['pid'],llm['pid'])
        self.assertIsNone(self.runtime.process,'text phase is always reclaimed')
        again=self.runtime.run('asr',{})
        self.assertNotEqual(first['pid'],again['pid'])
        self.wait(lambda:self.runtime.process is None)
    def test_live_preempts_text_and_text_retries_after_recording(self):
        results=[];errors=[]
        def summarize():
            try:results.append(self.runtime.run('llm',{'delay':1.5,'value':'unchanged request'}))
            except Exception as e:errors.append(e)
        thread=threading.Thread(target=summarize);thread.start()
        self.wait(lambda:self.runtime.state=='running')
        oldpid=self.runtime.process.pid;self.priority.start('live')
        response=self.runtime.run('asr',{'value':'live audio'},live=True)
        self.assertEqual(response['value'],'live audio');self.assertNotEqual(response['pid'],oldpid)
        self.assertTrue(thread.is_alive(),'summary waits while recording priority lease is active')
        self.priority.stop('live');thread.join(8)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(results[0]['value'],'unchanged request')
    def test_background_waits_without_blocking_live_lock(self):
        self.priority.start('rec');done=[]
        thread=threading.Thread(target=lambda:done.append(self.runtime.run('asr',{'value':'video'})));thread.start()
        self.wait(lambda:self.runtime.status()['waiting_inference']==1)
        self.assertEqual(self.runtime.run('asr',{'value':'live'},live=True)['value'],'live')
        self.assertEqual(done,[]);self.priority.stop('rec');thread.join(5)
        self.assertEqual(done[0]['value'],'video')
    def test_worker_failure_does_not_hang_and_can_retry(self):
        with self.assertRaises((RuntimeError,EOFError,ConnectionResetError)):self.runtime.run('asr',{'crash':True})
        self.assertEqual(self.runtime.state,'error');self.assertIsNone(self.runtime.process)
        self.assertEqual(self.runtime.run('asr',{'value':'retry'})['value'],'retry')
    def test_status_does_not_expose_content_or_paths(self):
        self.runtime.run('asr',{'value':'PRIVATE-CONTENT'})
        state=str(self.runtime.status())
        self.assertNotIn('PRIVATE-CONTENT',state);self.assertNotIn(self.temp.name,state)
        self.assertIn('16384',state)


class ServerRuntimeIntegrationTests(unittest.TestCase):
    def test_summary_retains_original_context_and_output_budget(self):
        import app
        from unittest.mock import Mock,patch
        runtime=Mock();runtime.run.return_value='自然总结'
        with patch.object(app,'low_runtime',runtime),patch.object(app.recording_priority,'wait_for_background'):
            self.assertEqual(app.generate('tingdu-qwen:latest','原文','自然总结'),'自然总结')
        op,payload=runtime.run.call_args.args
        self.assertEqual(op,'llm');self.assertEqual(payload['options']['num_ctx'],16384)
        self.assertEqual(payload['options']['num_predict'],2048);self.assertEqual(payload['keep_alive'],0)
        self.assertEqual(payload['model'],'tingdu-qwen:latest')
    def test_health_detects_legacy_and_v2_without_starting_model_service(self):
        import app,sys
        from pathlib import Path
        from unittest.mock import Mock,patch
        for base in ('manifests/registry.ollama.ai/library','manifests-v2/ollama.com/library'):
            with self.subTest(base=base),tempfile.TemporaryDirectory() as tmp:
                cache=Path(tmp);blob=cache/'blobs'/'sha256-test';blob.parent.mkdir();blob.write_text('{}')
                manifest=cache/base/'tingdu-qwen/latest';manifest.parent.mkdir(parents=True);manifest.symlink_to(blob)
                runtime=Mock();runtime.config={'ollama_models':tmp,'ollama_bin':sys.executable}
                with patch.object(app,'low_runtime',runtime),patch.dict(os.environ,{'TINGDU_LLM_MODEL':'tingdu-qwen:latest'}),patch.object(app.httpx,'get',side_effect=AssertionError('health must not start or call the model service')):
                    self.assertEqual(app.health()['models'],['tingdu-qwen:latest'])
                    blob.unlink()
                    self.assertEqual(app.health()['models'],[],'dangling cache links are not ready')
    def test_runtime_api_and_origin_allowlist(self):
        import app
        from fastapi.testclient import TestClient
        from unittest.mock import Mock,patch
        runtime=Mock();runtime.status.return_value={'profile':'server-2gb','public_ready':False,'state':'idle'}
        with patch.object(app,'low_runtime',runtime),patch.object(app,'LOW_MEMORY',True),patch.dict(os.environ,{'TINGDU_ALLOWED_ORIGINS':'https://tingdu.online'}):
            c=TestClient(app.app)
            r=c.get('/api/runtime',headers={'Origin':'https://tingdu.online'})
            self.assertEqual(r.status_code,200);self.assertFalse(r.json()['public_ready'])
            self.assertNotIn('processing_directory',r.json())
            self.assertEqual(c.get('/api/runtime',headers={'Origin':'https://evil.test'}).status_code,403)
            self.assertEqual(c.get('/api/runtime',headers={'Host':'evil.test'}).status_code,403)

if __name__=='__main__':unittest.main()
