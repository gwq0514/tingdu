"""Frozen local engine entrypoint. No recordings, cookies or secrets are bundled."""
import os,sys,runpy
from pathlib import Path
ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
if os.environ.get('TINGDU_DATA_DIR'):
    (Path(os.environ['TINGDU_DATA_DIR'])/'xhs-support').mkdir(parents=True,exist_ok=True)
if '--xhs-worker' in sys.argv:
    runpy.run_path(str(ROOT/'xhs_worker.py'),run_name='__main__')
else:
    import uvicorn
    import app
    uvicorn.run(app.app,host='127.0.0.1',port=int(os.environ.get('TINGDU_PORT','18765')),access_log=False)
