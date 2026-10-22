# PLACEHOLDER LLM stub (Member 1 skeleton). Member 3 replaces it; keep port 8002 and /v1/chat/completions.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY services/llm_stub/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY services/llm_stub/stub.py ./stub.py
EXPOSE 8002
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8002/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "stub:app", "--host", "0.0.0.0", "--port", "8002", "--no-access-log"]
