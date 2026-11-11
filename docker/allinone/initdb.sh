#!/bin/bash
# Lancé une seule fois, sur un volume vide, par l'image PostgreSQL (serveur temporaire sur le socket local) :
# restauration de la base, déploiement (migrations, rôles, fiches MCP), compte de lecture du serveur MCP.
set -euo pipefail
cd /opt/neolab/IDEA
py=/opt/neolab/venv/bin/python
export WAREHOUSE_POSTGRES_HOST=/var/run/postgresql WAREHOUSE_POSTGRES_PORT=5432 \
       WAREHOUSE_POSTGRES_DB="$POSTGRES_DB" WAREHOUSE_POSTGRES_USER="$POSTGRES_USER" \
       WAREHOUSE_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
trap 'echo "[neolab] ÉCHEC à la ligne $LINENO (voir les messages ci-dessus)"' ERR
echo "[neolab] 1/3 restauration de la base (quelques minutes)"
# The dump carries PostGIS's tiger geocoder (created by the former postgis/postgis image), which the warehouse
# never uses and recent PostGIS no longer ships: left out of the restore. Parallel restore (index builds).
list=$(mktemp)
pg_restore -l /opt/neolab/neolab.dump | grep -viE 'tiger' > "$list"
jobs=$(nproc 2>/dev/null || echo 2); [ "$jobs" -gt 4 ] && jobs=4
errors=$(mktemp)
pg_restore --no-owner --no-acl -j "$jobs" -L "$list" -h /var/run/postgresql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    /opt/neolab/neolab.dump 2> "$errors" || true
if grep -q "ERROR" "$errors"; then grep -A3 "ERROR" "$errors" | head -40; false; fi
rm -f "$list" "$errors"
echo "[neolab] 2/3 déploiement (migrations, rôles, fiches MCP)"
report=$("$py" scripts/deploy_warehouse_postgres.py --check 2>&1 || true)
if ! printf '%s\n' "$report" | grep -q "^PRÊT"; then
    printf '%s\n' "$report" | tail -30
    echo "[neolab] ÉCHEC : le warehouse n'est pas prêt"
    exit 1
fi
echo "[neolab] 3/3 compte de lecture du serveur MCP"
bundle=$(mktemp -d)
WAREHOUSE_PUBLIC_HOST=127.0.0.1 WAREHOUSE_PUBLIC_PORT=5432 \
    "$py" scripts/warehouse_user.py create lecture_mcp --all-access --out-dir "$bundle" >/dev/null
NEOLAB_WAREHOUSE_CREDENTIALS="$NEOLAB_STATE/credentials.env" \
    "$py" scripts/warehouse_connect.py init --from-file "$bundle/lecture_mcp.env" >/dev/null
rm -rf "$bundle"
touch "$NEOLAB_STATE/ready"
echo "[neolab] PRÊT"
