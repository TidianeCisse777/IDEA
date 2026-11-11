#!/bin/bash
# Lancé une seule fois, sur un volume vide, par l'image PostgreSQL (serveur temporaire sur le socket local) :
# restauration de la base, déploiement (migrations, rôles, fiches MCP), compte de lecture du serveur MCP.
set -euo pipefail
cd /opt/neolab/IDEA
py=/opt/neolab/venv/bin/python
export WAREHOUSE_POSTGRES_HOST=/var/run/postgresql WAREHOUSE_POSTGRES_PORT=5432 \
       WAREHOUSE_POSTGRES_DB="$POSTGRES_DB" WAREHOUSE_POSTGRES_USER="$POSTGRES_USER" \
       WAREHOUSE_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
echo "[neolab] 1/3 restauration de la base (quelques minutes)"
"$py" scripts/backup_warehouse.py --restore /opt/neolab/neolab.dump --yes
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
    "$py" scripts/warehouse_user.py create neolab_lecture --all-access --out-dir "$bundle" >/dev/null
NEOLAB_WAREHOUSE_CREDENTIALS="$NEOLAB_STATE/credentials.env" \
    "$py" scripts/warehouse_connect.py init --from-file "$bundle/neolab_lecture.env" >/dev/null
rm -rf "$bundle"
touch "$NEOLAB_STATE/ready"
echo "[neolab] PRÊT"
