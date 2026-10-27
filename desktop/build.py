"""Reproducible allowlist-only staging. Never copies user records or credentials."""
import hashlib,json,shutil,subprocess,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'build'/'desktop-resources'
sys.path.insert(0,str(ROOT))
from audio_processing import ASSETS
from scripts.install_sensevoice import FILES

def copy_file(source,target,expected=None):
    if not source.is_file():raise FileNotFoundError(source)
    if expected and hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise RuntimeError(f'Model checksum mismatch: {source.name}')
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)

def main():
    if sys.platform!='darwin':raise RuntimeError('Build on macOS')
    upstream=ROOT/'build'/'upstream'
    shutil.copytree(ROOT/'third_party/XHS-Downloader',upstream,dirs_exist_ok=True)
    for name in ['source/module/static.py','source/translation/translate.py']:
        p=upstream/name;s=p.read_text()
        replacement="Path(os.environ['TINGDU_DATA_DIR']) / 'xhs-support'" if 'module/static' in name else "Path(sys._MEIPASS)"
        s='import os\n'+s.replace('Path(sys.executable).resolve().parent',replacement)
        p.write_text(s)
    (ROOT/'build').mkdir(exist_ok=True)
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--name','tingdu-engine','--onedir','--target-arch','arm64','--distpath',str(ROOT/'build'/'frozen'),'--workpath',str(ROOT/'build'/'pyinstaller'),'--specpath',str(ROOT/'build'), '--paths',str(ROOT), '--paths',str(upstream)]
    for module in ['sherpa_onnx','curl_cffi','opencc','yt_dlp','xhshow','source']:
        args+=['--collect-all',module]
    for module in ['source','app','meetings','subscriptions','audio_processing','live_speakers','asr_vocabulary','sensevoice_asr','uvicorn.logging','uvicorn.loops.auto','uvicorn.protocols.http.auto','uvicorn.protocols.websockets.auto','uvicorn.lifespan.on']:
        args+=['--hidden-import',module]
    for source,target in [('static','static'),('xhs_worker.py','.'),('third_party/XHS-Downloader/locale','locale')]:
        args+=['--add-data',str(ROOT/source)+':'+target]
    args += [str(ROOT/'desktop'/'engine.py')]
    if '--stage-only' not in sys.argv:subprocess.run(args,cwd=ROOT,check=True,env={**os.environ,'PYTHONPATH':str(upstream)+os.pathsep+str(ROOT)})
    if STAGE.exists():shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    shutil.copytree(ROOT/'build'/'frozen'/'tingdu-engine',STAGE/'backend')
    (STAGE/'backend'/'_internal'/'xhs-support').mkdir(exist_ok=True)
    for name,checksum in FILES.items():copy_file(ROOT/'data/models/sensevoice'/name,STAGE/'models/sensevoice'/name,checksum)
    for name,asset in ASSETS.items():copy_file(ROOT/'data/models/audio'/name,STAGE/'models/audio'/name,asset['sha256'])
    components=json.loads((ROOT/'third_party/desktop-components.json').read_text())
    copy_file(ROOT/'data/llm/qwen3-0.6b.gguf',STAGE/'llm/qwen3-0.6b.gguf',components['qwen']['sha256'])
    copy_file(ROOT/'data/llm/Modelfile',STAGE/'llm/Modelfile')
    shutil.copytree(ROOT/'vendor/ollama/ollama/0.40.3/libexec',STAGE/'ollama',ignore=shutil.ignore_patterns('mlx_metal_v3'))
    copy_file(ROOT/'desktop/node_modules/ffmpeg-static/ffmpeg',STAGE/'bin/ffmpeg')
    print('Staged allowlisted desktop engine at',STAGE)

if __name__=='__main__':main()
