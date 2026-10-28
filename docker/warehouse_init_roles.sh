#!/bin/sh
# Docker first-init hook: create the warehouse read roles after every DDL file.
# Passwords arrive through the container environment, never through argv.
set -eu
psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -f /opt/warehouse/warehouse_roles.sql
