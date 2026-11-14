#!/bin/sh
# Start as root so the Fly volume can be made writable, then drop privileges.
set -e
mkdir -p /data
if [ "$(id -u)" = "0" ]; then
  chown -R appuser:appuser /data
  exec runuser -u appuser -- "$0" "$@"
fi
flask db upgrade
exec gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers 1 --threads 2 --timeout 120 run:app
