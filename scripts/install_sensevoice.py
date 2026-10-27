"""Explicit installation of publisher's SenseVoiceSmall INT8 export.
Set HTTPS_PROXY if your network needs a proxy. No audio is uploaded.
"""
import hashlib
from pathlib import Path
import httpx

BASE='https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/'
FILES={
 'model.int8.onnx':'c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51',
 'tokens.txt':'f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc',
}
root=Path(__file__).resolve().parents[1]/'data'/'models'/'sensevoice'

def install():
    root.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=120,follow_redirects=True) as client:
        for name,expected in FILES.items():
            path=root/name
            if path.exists() and hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==expected:
                print(name,'already verified');continue
            temp=path.with_suffix('.download')
            try:
                digest=hashlib.sha256()
                with client.stream('GET',BASE+name) as response:
                    response.raise_for_status()
                    with temp.open('wb') as out:
                        for chunk in response.iter_bytes():out.write(chunk);digest.update(chunk)
                if digest.hexdigest()!=expected:raise RuntimeError(name+' checksum mismatch')
                temp.replace(path);print(name,'installed and verified')
            finally:
                temp.unlink(missing_ok=True)

if __name__=='__main__':install()
