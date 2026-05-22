#!/usr/bin/env bash
set -e

MIGRATIONS_DIR="$(dirname "$0")/migrations"

echo "Running all migrations in $MIGRATIONS_DIR..."

for f in $(ls "$MIGRATIONS_DIR"/*.sql | sort); do
    echo "  -> $f"
    docker compose exec -T db psql -U andespace -d andespace < "$f"
done

echo "Done."
