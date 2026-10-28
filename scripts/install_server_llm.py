"""Install the exact desktop GGUF and initialize only the pilot Ollama cache.
Run while the pilot has no inference work. Never pulls a replacement model.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/gwq0514/tingdu/releases/download/v1.1.0-mac-preview/qwen3-0.6b.gguf'


def main():
    if os.environ.get('TINGDU_PROFILE') != 'server-2gb':
        raise RuntimeError('This installer is only for the isolated server-2gb pilot')
    data = Path(os.environ['TINGDU_DATA_DIR']).resolve()
    destination = data / 'llm' / 'qwen3-0.6b.gguf'
    expected = json.loads((ROOT / 'third_party/desktop-components.json').read_text())['qwen']['sha256']
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temp = destination.with_suffix('.gguf.download')
        digest = hashlib.sha256()
        with httpx.stream('GET', URL, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with temp.open('wb') as output:
                for chunk in response.iter_bytes():
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError('Downloaded GGUF checksum mismatch; no model initialized')
        temp.replace(destination)
    with destination.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
            raise RuntimeError('Existing GGUF checksum mismatch; no model initialized')
    print('Pinned full Q8 GGUF checksum verified', flush=True)
    model_file = destination.parent / 'Modelfile'
    model_file.write_text('FROM ./qwen3-0.6b.gguf\nPARAMETER num_ctx 8192\nPARAMETER temperature 0.2\n')
    host = '127.0.0.1:11435'
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 11435)) == 0:
            raise RuntimeError('Pilot model port is occupied; wait for inference to finish')
    binary = os.environ['TINGDU_OLLAMA_BIN']
    env = {**os.environ, 'OLLAMA_HOST': host, 'OLLAMA_MODELS': str(data / 'ollama'),
           'OLLAMA_NO_CLOUD': '1', 'OLLAMA_MAX_LOADED_MODELS': '1', 'OLLAMA_NUM_PARALLEL': '1'}
    process = subprocess.Popen([binary, 'serve'], env=env, start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url='http://' + host, trust_env=False, timeout=2) as client:
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError('Pilot Ollama exited before initialization')
                try:
                    client.get('/api/tags').raise_for_status()
                    break
                except httpx.HTTPError:
                    time.sleep(.2)
            else:
                raise RuntimeError('Pilot Ollama startup timeout')
        subprocess.run([binary, 'create', 'tingdu-qwen', '-f', str(model_file)],
                       env=env, check=True, timeout=300)
        print('Pilot cache initialized; inference still uses the original 16K request parameters', flush=True)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == '__main__':
    main()
