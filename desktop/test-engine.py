"""Packaged backend integration test with temporary synthetic data only."""
import os,subprocess,tempfile,time,wave,json
from pathlib import Path
import httpx,numpy as np
ROOT=Path(__file__).resolve().parents[1];base=ROOT/'build/desktop-resources'
with tempfile.TemporaryDirectory(prefix='tingdu-desktop-test-') as tmp:
    data=Path(tmp);(data/'models').symlink_to(base/'models',target_is_directory=True)
    env={**os.environ,'TINGDU_DATA_DIR':str(data),'TINGDU_PORT':'18767','PATH':str(base/'bin')+os.pathsep+os.environ['PATH']}
    with (data/'engine.log').open('w') as log:
        p=subprocess.Popen([str(base/'backend/tingdu-engine')],env=env,stdout=log,stderr=log)
        c=httpx.Client(base_url='http://127.0.0.1:18767',timeout=15,trust_env=False)
        try:
            for _ in range(120):
                if p.poll() is not None:raise RuntimeError((data/'engine.log').read_text())
                try:
                    if c.get('/api/storage').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.25)
            else:raise RuntimeError('Engine startup timeout')
            assert c.get('/api/storage').json()['processing_directory']==str(data.resolve())
            assert c.get('/').status_code==200
            assert c.get('/api/jobs').json()==[]
            assert c.post('/api/import',headers={'Origin':'https://evil.test'},json={'text':'测试'}).status_code==403
            r=c.post('/api/import',headers={'Origin':'http://127.0.0.1:18767'},json={'text':'这是桌面版的测试正文。','title':'桌面测试'})
            assert r.status_code==200,r.text
            # A synthetic local audio file tests frozen ONNX runtime, not the actual microphone.
            audio=data/'synthetic.wav'
            with wave.open(str(audio),'wb') as w:w.setparams((1,2,16000,0,'NONE',''));w.writeframes((np.sin(np.arange(32000)*.1)*100).astype('<i2').tobytes())
            with audio.open('rb') as f:r=c.post('/api/upload',files={'file':('synthetic.wav',f,'audio/wav')})
            assert r.status_code==200,r.text
            jid=r.json()['id']
            for _ in range(120):
                item=c.get('/api/jobs/'+jid).json()
                if item['status'] in ('done','error'):break
                time.sleep(.5)
            assert item['status']=='done',item
            assert item['asr_model']=='sensevoice'
            # Frozen subprocess dispatch must import XHS and reach JSON parsing.
            worker=subprocess.run([str(base/'backend/tingdu-engine'),'--xhs-worker'],input='{}',text=True,capture_output=True,env=env,timeout=30)
            assert "KeyError: 'path'" in worker.stderr,worker.stderr[-3000:]
            print('Frozen engine: isolated data, origin guard, import, bundled FFmpeg + SenseVoice and XHS worker OK')
        finally:
            p.terminate()
            try:p.wait(timeout=8)
            except subprocess.TimeoutExpired:p.kill();p.wait()
