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
set -a
# shellcheck disable=SC1091
. "$NEOLAB_STATE/secrets.env"
set +a
exec docker-entrypoint.sh "$@"
