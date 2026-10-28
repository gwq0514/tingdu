"""Synthetic capacity check; creates test-only resources, never captures a microphone.
Run inside the isolated pilot container with no other jobs. Takes at least 10 minutes.
A sampled cgroup peak includes all container processes and file cache.
This repeated single-speaker fixture cannot validate real meeting ASR/diarization accuracy.
"""
import httpx,time,json,io,wave,threading,hashlib
from pathlib import Path
c=httpx.Client(base_url='http://127.0.0.1:8768',timeout=600,trust_env=False)
response=httpx.get('https://github.com/gwq0514/tingdu/releases/download/v1.1.0-mac-preview/tingdu-meeting-qa.wav',follow_redirects=True,timeout=90)
response.raise_for_status();raw=response.content
if hashlib.sha256(raw).hexdigest()!='b36b434509085167dc64a097bdf6f78d768e1be31fde65ea196e54008316577e':raise RuntimeError('Synthetic fixture checksum mismatch')
with wave.open(io.BytesIO(raw)) as w: frames=w.readframes(w.getnframes())
def wav(data):
 b=io.BytesIO()
 with wave.open(b,'wb') as w:w.setparams((1,2,16000,0,'NONE',''));w.writeframes(data)
 return b.getvalue()
peak=[0];monitoring=[True]
def monitor():
 while monitoring[0]:
  for p in ('/sys/fs/cgroup/memory.current','/sys/fs/cgroup/memory/memory.usage_in_bytes'):
   try:peak[0]=max(peak[0],int(Path(p).read_text()))
   except (OSError,ValueError):pass
  time.sleep(.2)
threading.Thread(target=monitor,daemon=True).start()
start=time.monotonic();data=wav((frames*21)[:180*32000]);r=c.post('/api/upload',files={'file':('synthetic-180s.wav',data,'audio/wav')});r.raise_for_status();jid=r.json()['id'];Path('/data/benchmark-jid').write_text(jid)
deadline=time.monotonic()+1200
while time.monotonic()<deadline:
 rec=c.get('/api/jobs/'+jid).json()
 if rec['status'] in ('done','error'):break
 time.sleep(1)
print('IMPORT_180S',json.dumps({'seconds':round(time.monotonic()-start,2),'status':rec['status'],'chars':len(rec.get('text','')),'peak_MiB':round(peak[0]/1048576,1)}),flush=True)
r=c.post('/api/meetings',json={'title':'Synthetic 10-minute capacity test','llm_model':''});r.raise_for_status();mid=r.json()['id'];Path('/data/live-benchmark-jid').write_text(mid)
chunk=wav((frames*2)[:65536*2]);start=time.monotonic();maximum=0
for sequence in range(147):
 due=start+sequence*4.096
 if time.monotonic()<due:time.sleep(due-time.monotonic())
 r=c.post('/api/meetings/'+mid+'/chunks',data={'sequence':str(sequence)},files={'file':('chunk.wav',chunk,'audio/wav')});r.raise_for_status()
 rec=c.get('/api/jobs/'+mid).json();backlog=sequence+1-rec['transcribed_chunks'];maximum=max(maximum,backlog)
 if sequence%15==0:print('LIVE_PROGRESS',json.dumps({'seconds':round(time.monotonic()-start,1),'sent':sequence+1,'transcribed':rec['transcribed_chunks'],'backlog':backlog,'peak_MiB':round(peak[0]/1048576,1)}),flush=True)
c.post('/api/meetings/'+mid+'/finish',json={'chunks':147}).raise_for_status()
deadline=time.monotonic()+1200
while time.monotonic()<deadline:
 rec=c.get('/api/jobs/'+mid).json()
 if rec['status'] in ('done','error') and rec.get('diarization_status') not in ('queued','running'):break
 time.sleep(2)
monitoring[0]=False
result={'seconds':round(time.monotonic()-start,2),'audio_seconds':rec.get('duration'),'status':rec['status'],'transcribed':rec['transcribed_chunks'],'failed':rec['failed_chunks'],'max_observed_backlog':maximum,'live_speakers':rec.get('live_speaker_count'),'live_status':rec.get('live_diarization_status'),'final_diarization':rec.get('diarization_status'),'peak_MiB':round(peak[0]/1048576,1)}
Path('/data/extended-result.json').write_text(json.dumps(result));print('LIVE_FINAL',json.dumps(result),flush=True)

if result["status"]!="done" or result["failed"] or result["final_diarization"] not in ("done","empty"):raise SystemExit(1)
