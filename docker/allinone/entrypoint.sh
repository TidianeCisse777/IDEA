#!/bin/bash
# Premier démarrage : mots de passe générés et gardés dans le volume (jamais affichés), puis le démarrage
# standard de l'image PostgreSQL, qui lance initdb.sh une seule fois sur un volume vide.
set -euo pipefail
mkdir -p "$NEOLAB_STATE"
chown postgres:postgres /var/lib/postgresql/data "$NEOLAB_STATE"
chmod 700 "$NEOLAB_STATE"
if [ ! -f "$NEOLAB_STATE/secrets.env" ]; then
    gen() { python3 -c 'import secrets; print(secrets.token_urlsafe(24))'; }
    (umask 077; printf 'POSTGRES_PASSWORD=%s\nWAREHOUSE_READER_PASSWORD=%s\nWAREHOUSE_NAVIGATOR_PASSWORD=%s\n' \
        "$(gen)" "$(gen)" "$(gen)" > "$NEOLAB_STATE/secrets.env")
    chown postgres:postgres "$NEOLAB_STATE/secrets.env"
fi
# A first start that stopped before the end (error, computer switched off) leaves a database without the
# « ready » mark; PostgreSQL would then skip its initialisation forever. Start it again from scratch, at most
# three times, then stay up with the reason in the logs (docker logs neolab-warehouse) instead of looping.
if [ -s "$PGDATA/PG_VERSION" ] && [ ! -f "$NEOLAB_STATE/ready" ]; then
    attempts=$(cat "$NEOLAB_STATE/attempts" 2>/dev/null || echo 0)
    if [ "$attempts" -ge 3 ]; then
        echo "[neolab] ÉCHEC répété de l'installation : supprimer le conteneur et le volume puis relancer l'installeur."
        exec sleep infinity
    fi
    echo "[neolab] installation précédente interrompue : reprise depuis le début"
    rm -rf "$PGDATA"
fi
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo $(( $(cat "$NEOLAB_STATE/attempts" 2>/dev/null || echo 0) + 1 )) > "$NEOLAB_STATE/attempts"
fi
set -a
# shellcheck disable=SC1091
. "$NEOLAB_STATE/secrets.env"
set +a
exec docker-entrypoint.sh "$@"
