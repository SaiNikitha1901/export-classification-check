# Agent worker (Member 3): RQ worker on queue "runs", Prometheus metrics on :9100.
# Build context is the repo root. Stateless: safe with --scale agent-worker=N.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/models/hf TORCH_HOME=/opt/models/torch PROMPTS_DIR=/srv/prompts
WORKDIR /srv
RUN pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
COPY services/agent_worker/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
# Bake the toxicity model (L4) into the image so the worker never downloads at run time.
RUN python -c "from detoxify import Detoxify; Detoxify('original-small', device='cpu').predict('hello')"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
COPY shared /opt/shared
RUN pip install /opt/shared
COPY prompts /srv/prompts
COPY services/agent_worker/agent_worker ./agent_worker
COPY services/agent_worker/tests ./tests
# The stub's decision logic doubles as a zero-delay scripted LLM in the worker's tests.
COPY services/llm_stub/stub.py ./tests/llm_stub_app.py
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9100/metrics', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "agent_worker.run_worker"]
