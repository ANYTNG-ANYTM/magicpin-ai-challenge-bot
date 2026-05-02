#!/bin/sh
PORT=${PORT:-8080}
exec uvicorn bot:app --host 0.0.0.0 --port ${PORT}
