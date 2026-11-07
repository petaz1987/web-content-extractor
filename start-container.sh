#!/bin/sh
set -eu
exec gunicorn \
  --bind "0.0.0.0:${PORT:-5000}" \
  --workers 1 \
  --worker-class gthread \
  --threads 2 \
  --timeout 0 \
  --graceful-timeout 30 \
  --error-logfile - \
  main:app
