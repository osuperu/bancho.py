#!/usr/bin/env bash
set -euxo pipefail

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Checking MySQL TCP connection
scripts/wait-for-it.sh --timeout=60 $DB_HOST:$DB_PORT

# Checking Redis connection
scripts/wait-for-it.sh --timeout=60 $REDIS_HOST:$REDIS_PORT

python main.py
