"""Read-only Linux pilot preflight. Reports facts; does not promise 2 GiB viability."""
import json,os,platform,shutil,socket
from pathlib import Path

def report():
    mem={}
    if Path('/proc/meminfo').exists():
        for line in Path('/proc/meminfo').read_text().splitlines():
            key,value=line.split(':',1)
            if key in ('MemTotal','MemAvailable','SwapTotal','SwapFree'):mem[key]=int(value.split()[0])*1024
    path=Path(os.environ.get('TINGDU_DATA_DIR','/var/lib/tingdu-pilot/data'))
    base=path
    while not base.exists():base=base.parent
    bin=os.environ.get('TINGDU_OLLAMA_BIN','/usr/local/bin/ollama')
    with socket.socket() as s:occupied=s.connect_ex(('127.0.0.1',11435))==0
    checks={'linux':platform.system()=='Linux','python_313':__import__('sys').version_info>=(3,13),
            'ffmpeg':bool(shutil.which('ffmpeg')),'ollama_binary':Path(bin).is_file(),'managed_port_free':not occupied,
            'free_disk_over_5g':shutil.disk_usage(base).free>5*1024**3}
    from sensevoice_asr import available
    from audio_processing import model_status
    checks['asr_weights']=available(path);audio=model_status(path)
    checks.update(denoise_weights=audio['denoise_available'],speaker_weights=audio['diarization_available'])
    return {'platform':platform.platform(),'cpu_count':os.cpu_count(),'memory_bytes':mem,'checks':checks,
            'deployment':'validation-only','public_ready':False,'capacity_verified':False}
if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    print(json.dumps(report(),ensure_ascii=False,indent=2))
