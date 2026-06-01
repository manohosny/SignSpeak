#! /usr/bin/env bash

# Backend pre-start: wait for the database, run migrations, seed initial data.
#
# `set -euo pipefail` makes any failure abort the script immediately, so the
# `prestart` Compose service exits non-zero. Combined with the backend's
# `depends_on: prestart: condition: service_completed_successfully`, this
# guarantees the backend never starts against an un-migrated or unreachable
# database — a partial/failed migration can no longer slip through silently.
set -euo pipefail
set -x

# Let the DB start
echo "prestart: waiting for the database to accept connections..."
python app/backend_pre_start.py

# Run migrations
echo "prestart: applying Alembic migrations..."
alembic upgrade head

# Create initial data in DB
echo "prestart: seeding initial data..."
python app/initial_data.py

echo "prestart: completed successfully."
