# PLACEHOLDER retriever (Member 1 skeleton). Member 2 replaces it; keep port 8001 and the A.7 endpoints.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY services/retriever/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY shared /opt/shared
RUN pip install /opt/shared
COPY services/retriever/retriever ./retriever
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "retriever.app:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
