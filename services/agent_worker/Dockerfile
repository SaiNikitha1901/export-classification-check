# PLACEHOLDER worker (Member 1 skeleton). Member 3 replaces the agent code; keep the CMD contract:
# an RQ worker on queue "runs" exposing Prometheus metrics on :9100. Build context is the repo root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY services/agent_worker/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY shared /opt/shared
RUN pip install /opt/shared
COPY services/agent_worker/agent_worker ./agent_worker
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9100/metrics', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "agent_worker.run_worker"]
