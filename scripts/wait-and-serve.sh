#!/bin/bash
# Wait for bootstrap to finish (DB has properties) before starting uvicorn.
# Polls every 2 seconds for up to 10 minutes.

echo "Waiting for bootstrap to complete (properties in DB)..."

MAX_WAIT=600
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Check if properties table has rows
    COUNT=$(python -c "
from db.session import init_db, get_session
from db.models import Property
init_db()
s = get_session()
try:
    print(s.query(Property).count())
finally:
    s.close()
" 2>/dev/null)

    if [ "$COUNT" != "" ] && [ "$COUNT" -gt 0 ] 2>/dev/null; then
        echo "Bootstrap complete ($COUNT properties found). Starting API..."
        exec uvicorn serving.api:app --host 0.0.0.0 --port 8000
    fi

    sleep 2
    ELAPSED=$((ELAPSED + 2))
    echo "  Still waiting... (${ELAPSED}s)"
done

echo "ERROR: Bootstrap did not complete within ${MAX_WAIT}s. Starting API anyway."
exec uvicorn serving.api:app --host 0.0.0.0 --port 8000
