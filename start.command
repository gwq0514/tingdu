#!/bin/zsh
cd "$(dirname "$0")"
OLLAMA_BIN="$PWD/vendor/ollama/ollama/0.40.3/bin/ollama"
if [ -x "$OLLAMA_BIN" ] && ! curl -fs --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  OLLAMA_MODELS="$PWD/data/ollama" OLLAMA_NO_CLOUD=1 "$OLLAMA_BIN" serve > /tmp/tingdu-ollama.log 2>&1 &
fi
if curl -fs --max-time 2 http://127.0.0.1:8765/api/health >/dev/null; then
  open http://127.0.0.1:8765
  exit 0
fi
if [ ! -x .runtime/bin/python ]; then
  /opt/homebrew/bin/python3.13 -m venv .runtime || exit 1
  .runtime/bin/python -m pip install -r requirements.lock.txt || exit 1
fi
open http://127.0.0.1:8765
.runtime/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765
