"""Opt-in 2 GiB pilot scheduler. Same weights/parameters, one owned worker group.
The default desktop/local engine never enables this module's worker runtime.
"""
import atexit, multiprocessing as mp, os, signal, threading, time, json
from pathlib import Path

PROFILE='server-2gb'
AUDIO_OPS={'asr':'语音转写','enhance':'降噪处理','enhance_file':'整理降噪音频','live':'临时发言人标记','diarize_file':'校正发言人','clear_live':'整理录音'}

class Interrupted(Exception):pass

def worker_main(connection, phase, config):
    # All descendant processes belong to our group, never a user's existing Ollama.
    if hasattr(os,'setsid'):os.setsid()
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
    owned=None
    try:
        connection.send({'ready':True})
        if phase=='llm':
            connection.send({'progress':'loading'})
            import subprocess, httpx, socket
            host,port=config['ollama_host'].rsplit(':',1)
            with socket.socket() as probe:
                if probe.connect_ex((host,int(port)))==0:raise RuntimeError('managed model port already occupied')
            env={**os.environ,'OLLAMA_HOST':config['ollama_host'],'OLLAMA_MODELS':config['ollama_models'],
                 'OLLAMA_NO_CLOUD':'1','OLLAMA_NUM_PARALLEL':'1','OLLAMA_MAX_LOADED_MODELS':'1',
                 'OLLAMA_KEEP_ALIVE':'0','OLLAMA_NOPRUNE':'1','OLLAMA_NUM_THREADS':'1'}
            owned=subprocess.Popen([config['ollama_bin'],'serve'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            until=time.monotonic()+90
            while True:
                if owned.poll() is not None:raise RuntimeError('managed model service exited')
                try:
                    r=httpx.get(config['ollama_url']+'/api/tags',timeout=1,trust_env=False);r.raise_for_status();break
                except httpx.HTTPError:
                    if time.monotonic()>until:raise RuntimeError('model service startup timeout')
                    time.sleep(.2)
        asr=None
        while True:
            request=connection.recv();op=request['op'];p=request['payload']
            try:
                if op=='llm':
                    connection.send({'progress':'loading'});pieces=[];started=False
                    with httpx.stream('POST',config['ollama_url']+'/api/chat',json={**p,'stream':True},timeout=600,trust_env=False) as response:
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if not line:continue
                            event=json.loads(line)
                            if event.get('error'):raise RuntimeError('model inference failed')
                            text=event.get('message',{}).get('content','')
                            if text and not started:connection.send({'progress':'running'});started=True
                            pieces.append(text)
                    result=''.join(pieces)
                else:
                    import audio_processing as audio, live_speakers
                    models=audio.models_for(config['data'])
                    if op=='asr':
                        from sensevoice_asr import SenseVoiceModel
                        if asr is None:
                            connection.send({'progress':'loading'});asr=SenseVoiceModel(Path(config['data'])/'models/sensevoice')
                        connection.send({'progress':'running'})
                        segments,info=asr.transcribe(p['samples']);result=(list(segments),info)
                    elif op=='enhance':result=models.enhance(p['samples'],p.get('prefix'))
                    elif op=='enhance_file':result=models.enhance_file(p['source'],p['target'])
                    elif op=='diarize_file':result=models.diarize(audio.read_wav(p['source']))
                    elif op=='live':result=live_speakers.service(config['data']).process(p['jid'],p['samples'],p['segments'],p['offset'])
                    elif op=='clear_live':result=live_speakers.service(config['data']).clear(p['jid'])
                    else:raise ValueError('unknown operation')
                connection.send({'ok':True,'result':result})
            except Exception:
                # User content, filesystem paths and model service responses stay private.
                connection.send({'ok':False,'error':'模型处理未完成，原声与已有文字保留，可稍后重试。'})
    except (EOFError,BrokenPipeError):pass
    finally:
        if owned is not None:
            owned.terminate()
            try:owned.wait(timeout=3)
            except Exception:owned.kill()
        connection.close()

class Runtime:
    def __init__(self,data,priority,ollama_bin='',ollama_models='',ollama_host='127.0.0.1:11435',idle_seconds=30,target=worker_main):
        if not ollama_host.startswith('127.0.0.1:'):raise ValueError('managed model server must be loopback-only')
        self.priority=priority;self.idle_seconds=idle_seconds;self.target=target
        self.config={'data':str(Path(data).resolve()),'ollama_bin':ollama_bin,'ollama_models':str(Path(ollama_models or Path(data)/'ollama').resolve()),'ollama_host':ollama_host,'ollama_url':'http://'+ollama_host}
        self.condition=threading.Condition(threading.RLock());self.waiters=[];self.counter=0
        self.process=None;self.pipe=None;self.phase='';self.active='';self.state='idle';self.changed=time.monotonic();self.closed=False
        threading.Thread(target=self._reap,daemon=True,name='idle-model-reclaimer').start();atexit.register(self.close)
    def _stop(self):
        p=self.process;self.process=None;self.phase=''
        if self.pipe:self.pipe.close();self.pipe=None
        if p:
            if p.pid:
                try:os.killpg(p.pid,signal.SIGTERM)
                except (ProcessLookupError,PermissionError,AttributeError):
                    if p.is_alive():p.terminate()
            if not p.pid:
                p.close();return
            p.join(timeout=2)
            # A model server descendant can outlive its worker, so clear its owned group.
            try:os.killpg(p.pid,signal.SIGKILL)
            except (ProcessLookupError,PermissionError,AttributeError):pass
            if p.is_alive():p.kill();p.join(timeout=2)
            p.close()
    def _start(self,phase):
        if self.process and self.phase==phase and self.process.is_alive():return
        self.state='switching';self._stop();self.state='loading'
        context=mp.get_context('spawn');parent,child=context.Pipe()
        p=context.Process(target=self.target,args=(child,phase,self.config),daemon=False)
        self.process=p;self.pipe=parent;self.phase=phase;p.start();child.close()
        until=time.monotonic()+30
        while not parent.poll(.1):
            if not p.is_alive() or time.monotonic()>until:raise RuntimeError('模型进程启动失败，请检查服务器内存后重试。')
        if not parent.recv().get('ready'):raise RuntimeError('模型进程未就绪')
    def run(self,op,payload,live=False):
        rank=0 if live else 20 if op=='llm' else 10
        while True:
            with self.condition:
                if self.closed:raise RuntimeError('模型服务已停止')
                self.counter+=1;ticket=(rank,self.counter);self.waiters.append(ticket)
                try:
                    while self.active or ticket!=min(self.waiters) or (not live and self.priority.busy()):
                        self.condition.wait(.1)
                        if self.closed:raise RuntimeError('模型服务已停止')
                    self.active=op;self.state='loading'
                finally:self.waiters.remove(ticket)
            interrupted=False
            try:
                self._start('llm' if op=='llm' else 'audio')
                self.state='running';self.pipe.send({'op':op,'payload':payload})
                while True:
                    # Reclaim the entire owned group before giving the next live chunk memory.
                    if not live and self.priority.busy():raise Interrupted()
                    if not self.pipe.poll(.1):
                        if not self.process.is_alive():raise RuntimeError('模型进程已退出，可能内存不足；原声与已有文字仍保留。')
                        continue
                    reply=self.pipe.recv()
                    if reply.get('progress'):
                        self.state=reply['progress'];continue
                    break
                if not reply.get('ok'):raise RuntimeError(reply.get('error','处理未完成'))
                return reply.get('result')
            except Interrupted:
                interrupted=True
                with self.condition:self.state='yielding';self._stop()
            except Exception:
                with self.condition:self._stop();self.state='error'
                raise
            finally:
                with self.condition:
                    if op=='llm' or self.closed:self._stop()  # Never retain a text model alongside audio.
                    self.active='';self.changed=time.monotonic()
                    if self.state!='error':self.state='waiting' if interrupted else 'idle'
                    self.condition.notify_all()
            # Restart the interrupted operation from its durable input after recording ends.
    def status(self):
        with self.condition:
            busy=self.priority.busy()
            return {'profile':PROFILE,'state':self.state,'active':self.active,'phase':self.phase,
                    'operation_label':AUDIO_OPS.get(self.active,'生成内容总结 / 回答问题' if self.active=='llm' else ''),
                    'waiting_inference':len(self.waiters),'recording_priority':busy,'worker_loaded':bool(self.process),
                    'full_models':True,'context_tokens':16384,'public_ready':False}
    def _reap(self):
        while True:
            with self.condition:
                if self.closed:return
                if not self.active and self.process and time.monotonic()-self.changed>=self.idle_seconds:
                    self._stop();self.state='idle'
                self.condition.wait(.5)
    def close(self):
        with self.condition:
            self.closed=True
            # Call when requests have drained (ASGI shutdown); never stop another service.
            if not self.active:self._stop()
            self.condition.notify_all()

class ASRProxy:
    def __init__(self,runtime,live=False):self.runtime=runtime;self.live=live
    def transcribe(self,samples,**kwargs):return self.runtime.run('asr',{'samples':samples},self.live)
class AudioProxy:
    def __init__(self,runtime,live=False):self.runtime=runtime;self.live=live
    def enhance(self,samples,prefix=None):return self.runtime.run('enhance',{'samples':samples,'prefix':prefix},self.live)
    def enhance_file(self,source,target,checkpoint=lambda:None):return self.runtime.run('enhance_file',{'source':str(source),'target':str(target)})
class SpeakersProxy:
    def __init__(self,runtime):self.runtime=runtime
    def process(self,jid,samples,segments,offset):return self.runtime.run('live',dict(jid=jid,samples=samples,segments=segments,offset=offset),live=True)
    def clear(self,jid):
        if self.runtime.phase=='audio':self.runtime.run('clear_live',{'jid':jid},live=True)
