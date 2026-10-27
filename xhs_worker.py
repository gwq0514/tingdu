"""Run upstream XHS-Downloader in a separate process; cookies only travel over stdin."""
import asyncio, json, sys, os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
support=Path(os.environ.get('TINGDU_DATA_DIR',ROOT/'data'))/'xhs-support'
support.mkdir(parents=True,exist_ok=True)
os.environ.setdefault('TINGDU_XHS_HOME',str(support))
sys.path.insert(0,str(ROOT/'third_party/XHS-Downloader'))
from source import XHS
async def main():
    req=json.loads(sys.stdin.read())
    async with XHS(work_path=req['path'],folder_name='media',cookie=req.get('cookie',''),record_data=False,download_record=False,image_download=False,video_download=True,max_retry=2,timeout=20,author_archive=False) as xhs:
        result=await xhs.extract(req['url'],download=True,check_record=False)
    (Path(req['path'])/'xhs-result.json').write_text(json.dumps(result,ensure_ascii=False))
asyncio.run(main())
