"""Test the original summary request on a synthetic test resource, after audio work ends.
Usage: python deploy/2gb/benchmark_summary.py SYNTHETIC_RESOURCE_ID
The returned summary and metrics are saved only to the pilot data directory.
"""
import httpx,time,threading,json
from pathlib import Path
peak=[0];swap_peak=[0];running=[True]
def monitor():
 while running[0]:
  for name in ('/sys/fs/cgroup/memory.current','/sys/fs/cgroup/memory/memory.usage_in_bytes'):
   try:peak[0]=max(peak[0],int(Path(name).read_text()))
   except (OSError,ValueError):pass
  try:
   current=Path('/sys/fs/cgroup/memory.swap.current')
   swap=int(current.read_text()) if current.exists() else int(Path('/sys/fs/cgroup/memory/memory.memsw.usage_in_bytes').read_text())-int(Path('/sys/fs/cgroup/memory/memory.usage_in_bytes').read_text())
   swap_peak[0]=max(swap_peak[0],swap)
  except (OSError,ValueError):pass
  time.sleep(.1)
threading.Thread(target=monitor,daemon=True).start()
c=httpx.Client(base_url='http://127.0.0.1:8768',trust_env=False,timeout=600)
import sys
jid=sys.argv[1] if len(sys.argv)>1 else Path('/data/benchmark-jid').read_text();start=time.monotonic()
try:
 r=c.post('/api/jobs/'+jid+'/chat',json={'model':'tingdu-qwen:latest','summary':True})
 result={'status_code':r.status_code,'seconds':round(time.monotonic()-start,2),'peak_MiB':round(peak[0]/1048576,1),'peak_swap_MiB':round(swap_peak[0]/1048576,1),'response':r.json(),'runtime':c.get('/api/runtime').json()}
except Exception as exc:result={'error':type(exc).__name__,'seconds':round(time.monotonic()-start,2),'peak_MiB':round(peak[0]/1048576,1),'peak_swap_MiB':round(swap_peak[0]/1048576,1)}
running[0]=False;Path('/data/llm-result.json').write_text(json.dumps(result,ensure_ascii=False));print(json.dumps(result,ensure_ascii=False),flush=True)

if result.get("status_code")!=200 or not result.get("response",{}).get("answer","").strip():raise SystemExit(1)
