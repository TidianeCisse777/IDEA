#!/usr/bin/env bash
# Installe en une commande la copie partagée du warehouse NeoLab, depuis le dossier des zips décompressés :
#
#     bash installer.sh            # compte de lecture à votre nom d'utilisateur
#     bash installer.sh mon_nom    # ou à ce nom (minuscules, chiffres, _)
#
# Prérequis (LISEZMOI, partie 1) : Docker lancé, Python 3.10+, client PostgreSQL 16+, Node.js 18+.
# Relançable : chaque étape déjà faite est sautée. Les mots de passe sont générés, jamais affichés,
# et restent dans IDEA/.env.warehouse (lisible par vous seul).
# Linux, WSL (Windows) et macOS (bash 3.2) : pas de syntaxe propre à bash 4, pas de `timeout`.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
step() { printf '\n== %s\n' "$*"; }
fail() { printf '\nÉCHEC : %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
major() { printf '%s' "$1" | sed -E 's/^[^0-9]*([0-9]+).*/\1/'; }

account=${1:-$(id -un)}
account=$(printf '%s' "$account" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '_' | cut -c1-30)
case "$account" in [a-z]*) ;; *) account="u_$account" ;; esac
case "$account" in warehouse_*|pg_*|neolab) account="${account}_lecture" ;; esac
[ "${#account}" -ge 3 ] || account="${account}_neolab"

step "1/8 Outils"
have docker || fail "Docker introuvable : l'installer (LISEZMOI, partie 1)."
docker info >/dev/null 2>&1 || fail "Docker ne répond pas : lancer Docker Desktop (Windows, macOS) ou « sudo systemctl start docker » (Linux)."
docker compose version >/dev/null 2>&1 || fail "Docker Compose 2 introuvable : mettre Docker à jour."
have python3 || fail "Python 3 introuvable (LISEZMOI, partie 1)."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || fail "Python 3.10 ou plus requis ($(python3 --version))."
have psql || fail "Client PostgreSQL (psql) introuvable (LISEZMOI, partie 1)."
[ "$(major "$(psql --version | awk '{print $3}')")" -ge 16 ] || fail "psql 16 ou plus requis ($(psql --version))."
have node || fail "Node.js introuvable (LISEZMOI, partie 1)."
[ "$(major "$(node --version)")" -ge 18 ] || fail "Node.js 18 ou plus requis ($(node --version))."
if have sha256sum; then shacheck() { sha256sum -c "$1"; }; else shacheck() { shasum -a 256 -c "$1"; }; fi
echo "Docker, Python, psql, Node : OK"

step "2/8 Base de données : recoller les morceaux et vérifier"
sums=$(ls neolab_warehouse_*.dump.sha256 2>/dev/null | head -1)
[ -n "$sums" ] || fail "fichier .dump.sha256 introuvable : lancer ce script depuis le dossier des zips décompressés."
dump=${sums%.sha256}
if [ ! -f "$dump" ]; then
    ls "$dump".part* >/dev/null 2>&1 || fail "morceaux $dump.part* introuvables : décompresser les deux zips dans ce même dossier."
    cat "$dump".part* > "$dump.tmp" && mv "$dump.tmp" "$dump"
fi
if ! shacheck "$sums"; then
    rm -f "$dump"
    fail "la base est incomplète ou abîmée : retélécharger les deux zips, les décompresser ici, relancer."
fi

step "3/8 Code"
[ -d IDEA ] || tar xzf IDEA-code.tar.gz
cd IDEA

step "4/8 Python (environnement isolé .venv)"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q --disable-pip-version-check "psycopg[binary]" python-dotenv
echo "OK"

step "5/8 Mots de passe"
if [ ! -f .env.warehouse ]; then
    (umask 077; python3 - <<'PY'
import secrets
lines = open('example.warehouse.env', encoding='utf-8').read().splitlines()
out = [line.replace('CHANGER_MOI', secrets.token_urlsafe(18)) if not line.lstrip().startswith('#') else line for line in lines]
open('.env.warehouse', 'w', encoding='utf-8').write('\n'.join(out) + '\n')
PY
    )
    echo "trois mots de passe générés dans IDEA/.env.warehouse (non affichés)"
else
    echo "IDEA/.env.warehouse existe déjà : gardé"
fi
set -a
# shellcheck disable=SC1091
. ./.env.warehouse
set +a

step "6/8 Lancer la base (Docker ; le premier lancement télécharge environ 1 Go)"
compose() { docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml "$@"; }
compose up -d --build || fail "Docker n'a pas pu lancer la base (port ${WAREHOUSE_POSTGRES_PORT:-55432} ou ${WAREHOUSE_NAVIGATOR_PORT:-8090} déjà pris ? les changer dans IDEA/.env.warehouse, puis relancer)."
waited=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' neolab-warehouse-db 2>/dev/null)" = healthy ]; do
    [ "$waited" -lt 600 ] || fail "la base ne démarre pas : « docker logs neolab-warehouse-db » pour le détail."
    sleep 5; waited=$((waited + 5))
done
echo "base prête"

step "7/8 Installer les données (5 à 10 minutes)"
export PGHOST="$WAREHOUSE_POSTGRES_HOST" PGPORT="$WAREHOUSE_POSTGRES_PORT" PGUSER="$WAREHOUSE_POSTGRES_USER" \
       PGDATABASE="$WAREHOUSE_POSTGRES_DB" PGPASSWORD="$WAREHOUSE_POSTGRES_PASSWORD"
loaded=$(psql -X -At -c "SELECT count(*) FROM warehouse.ecotaxa_object" 2>/dev/null || echo 0)
unset PGPASSWORD
if [ "${loaded:-0}" -gt 0 ] 2>/dev/null; then
    echo "données déjà installées ($loaded objets) : restauration sautée"
else
    python scripts/backup_warehouse.py --restore "../$dump" --yes
fi
report=$(python scripts/deploy_warehouse_postgres.py --check 2>&1 || true)
printf '%s\n' "$report" | grep -E "ÉCHEC|PRÊT" || true
printf '%s\n' "$report" | grep -q "^PRÊT" || { printf '%s\n' "$report" | tail -30; fail "le warehouse n'est pas prêt (lignes ÉCHEC ci-dessus)."; }

step "8/8 Votre compte de lecture et votre assistant"
if python scripts/warehouse_connect.py check >/dev/null 2>&1; then
    echo "connexion déjà configurée : gardée"
else
    bundle=$(mktemp -d)
    python scripts/warehouse_user.py create "$account" --all-access --out-dir "$bundle" >/dev/null 2>&1 \
        || python scripts/warehouse_user.py rotate "$account" --out-dir "$bundle" >/dev/null \
        || fail "création du compte $account impossible."
    python scripts/warehouse_connect.py init --from-file "$bundle/$account.env" >/dev/null
    rm -rf "$bundle"
    echo "compte de lecture « $account » créé et enregistré"
fi
python scripts/warehouse_connect.py install-dbhub | tail -1
check=$(python scripts/warehouse_connect.py check 2>&1 || true)
printf '%s\n' "$check" | grep -q "PASS" || { printf '%s\n' "$check" | tail -15; fail "la connexion MCP ne passe pas (docs/WAREHOUSE_CONNECT.md, Dépannage)."; }
echo "connexion MCP : PASS"
python scripts/warehouse_connect.py workspace "$HOME/neolab-travail" >/dev/null
echo "dossier de travail : $HOME/neolab-travail"
server_python="$PWD/.venv/bin/python"
server_script="$PWD/scripts/warehouse_connect.py"
assistants=""
if have claude; then
    claude mcp list 2>/dev/null | grep -q neolab-warehouse \
        || claude mcp add --scope user neolab-warehouse -- "$server_python" "$server_script" run >/dev/null
    assistants="$assistants claude"
    echo "Claude Code : serveur neolab-warehouse enregistré"
fi
if have codex; then
    codex mcp list 2>/dev/null | grep -q neolab-warehouse \
        || codex mcp add neolab-warehouse -- "$server_python" "$server_script" run >/dev/null
    assistants="$assistants codex"
    echo "Codex : serveur neolab-warehouse enregistré"
fi

printf '\nINSTALLATION TERMINÉE.\n\n'
if [ -n "$assistants" ]; then
    first=$(printf '%s' "$assistants" | awk '{print $1}')
    printf 'Pour poser une question :\n    cd ~/neolab-travail && %s\n' "$first"
else
    printf 'Aucun assistant trouvé (claude, codex). Après en avoir installé un (LISEZMOI, partie 2), relancer ce script.\n'
fi
printf 'GitHub Copilot (VS Code) : dans IDEA, « python scripts/warehouse_connect.py config vscode » (LISEZMOI, partie 4).\n'
printf 'Les fois suivantes : lancer Docker, puis « cd %s && docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d ».\n' "$PWD"
