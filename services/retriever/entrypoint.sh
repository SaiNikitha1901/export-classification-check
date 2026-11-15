#!/bin/sh
# serve (default): build the index if the volume has none, then start the HTTP service.
# anything else:   run that command (e.g. `python -m retriever.ingest status`).
set -e
if [ "$1" = "serve" ]; then
  python -m retriever.ingest build --if-missing || echo '{"level":"ERROR","service":"retriever","event":"ingest_failed","msg":"index build failed; /health stays 503"}'
  exec uvicorn retriever.app:app --host 0.0.0.0 --port 8001 --no-access-log
fi
exec "$@"
