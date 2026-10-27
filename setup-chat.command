#!/bin/zsh
cd "$(dirname "$0")"
OLLAMA_BIN="$PWD/vendor/ollama/ollama/0.40.3/bin/ollama"
if [ ! -x "$OLLAMA_BIN" ]; then OLLAMA_BIN="$(command -v ollama)"; fi
if [ ! -x "$OLLAMA_BIN" ]; then
  echo '请先安装 Ollama：https://ollama.com/download'
  exit 1
fi
if ! curl -fs --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  OLLAMA_MODELS="$PWD/data/ollama" OLLAMA_NO_CLOUD=1 "$OLLAMA_BIN" serve > /tmp/tingdu-ollama.log 2>&1 &
  sleep 2
fi
if [ -f data/llm/qwen3-0.6b.gguf ]; then
  "$OLLAMA_BIN" create tingdu-qwen -f data/llm/Modelfile
else
  "$OLLAMA_BIN" pull qwen3:1.7b
fi
echo '完成，请刷新听读页面。'
