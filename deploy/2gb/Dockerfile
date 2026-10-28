FROM ollama/ollama:0.40.3 AS model_runtime
FROM python:3.13-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates libgomp1 libopenblas0-pthread libvulkan1 && rm -rf /var/lib/apt/lists/*
COPY --from=model_runtime /bin/ollama /usr/local/bin/ollama
COPY --from=model_runtime /usr/lib/ollama /usr/local/lib/ollama
RUN test -x /usr/local/lib/ollama/llama-server
WORKDIR /app
COPY requirements.lock.txt /app/
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY . /app
ENV TINGDU_PROFILE=server-2gb TINGDU_DATA_DIR=/data TINGDU_PORT=8768 TINGDU_OLLAMA_BIN=/usr/local/bin/ollama OLLAMA_MODELS=/data/ollama HOME=/data PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
USER 1000:1000
CMD ["python","-m","uvicorn","app:app","--host","0.0.0.0","--port","8768","--workers","1","--no-access-log"]
