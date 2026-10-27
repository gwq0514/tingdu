import os
"""Explicit, checksum-verified installation from the model publisher's releases."""
import hashlib
import io
import sys
import tarfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from audio_processing import ASSETS
root=Path(os.environ.get('TINGDU_DATA_DIR',Path(__file__).resolve().parents[1]/'data'))/'models'/'audio';root.mkdir(parents=True,exist_ok=True)
for name,asset in ASSETS.items():
    path=root/name
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==asset['sha256']:
        print(name,'already verified');continue
    with httpx.Client(timeout=120,follow_redirects=True) as client:
        response=client.get(asset['url']);response.raise_for_status();data=response.content
    if asset.get('member'):
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:bz2') as archive:
            member=next(m for m in archive.getmembers() if m.isfile() and m.name.endswith('/'+asset['member']))
            data=archive.extractfile(member).read()
    if hashlib.sha256(data).hexdigest()!=asset['sha256']:raise RuntimeError(name+' checksum mismatch; installation aborted')
    temp=path.with_suffix('.download');temp.write_bytes(data);temp.replace(path);print(name,'installed and verified')
