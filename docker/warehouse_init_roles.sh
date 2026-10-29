#!/bin/sh
# Docker first-init hook, run after every DDL file: creates the read roles, then
# records the release with the SHA-256 of each init file. Passwords arrive
# through the container environment, never through argv.
set -eu
psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -f /opt/warehouse/warehouse_roles.sql

manifest="["
for file in /docker-entrypoint-initdb.d/*.sql /opt/warehouse/warehouse_roles.sql /opt/warehouse/warehouse_release.sql; do
  [ -f "$file" ] || continue
  sum=$(sha256sum "$file" | cut -d' ' -f1)
  manifest="$manifest{\"file\": \"$(basename "$file")\", \"sha256\": \"$sum\"},"
done
manifest="${manifest%,}]"

psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v method=docker-init -v migrations="$manifest" -f /opt/warehouse/warehouse_release.sql
