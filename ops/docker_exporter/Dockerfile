FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install prometheus-client==0.21.1
COPY ops/docker_exporter/exporter.py /srv/exporter.py
EXPOSE 9417
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9417/metrics', timeout=4).status == 200 else 1)"
CMD ["python", "/srv/exporter.py"]
