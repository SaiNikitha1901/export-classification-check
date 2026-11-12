# Retriever (Member 2): ingestion CLI + retrieval HTTP service (A.7). Build context = repo root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CORPUS_DIR=/srv/corpus HF_HOME=/data/index/hf_cache ANONYMIZED_TELEMETRY=False \
    TOKENIZERS_PARALLELISM=false
WORKDIR /srv
# CPU-only torch keeps the image ~1.5 GB smaller than the default CUDA build.
RUN pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
COPY services/retriever/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY shared /opt/shared
RUN pip install /opt/shared
COPY corpus ./corpus
COPY services/retriever/retriever ./retriever
COPY services/retriever/tests ./tests
COPY services/retriever/entrypoint.sh ./entrypoint.sh
# Windows checkouts (git autocrlf) give the script CRLF endings, which /bin/sh cannot run.
RUN sed -i 's/\r$//' ./entrypoint.sh && chmod +x ./entrypoint.sh
EXPOSE 8001
# Unhealthy until the index is loaded. The first start downloads the embedding model and builds the index.
HEALTHCHECK --interval=10s --timeout=5s --start-period=300s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["./entrypoint.sh"]
CMD ["serve"]
