#!/usr/bin/env bash
# Installe en une commande la copie partagée du warehouse NeoLab, outils compris :
#
#     bash installer.sh            # compte de lecture à votre nom d'utilisateur
#     bash installer.sh mon_nom    # ou à ce nom (minuscules, chiffres, _)
#
# macOS : installe ce qui manque avec Homebrew (Python, Node, client PostgreSQL, Docker Desktop).
# Ubuntu et WSL (Windows) : installe ce qui manque avec apt (Docker vient de Docker Desktop sous Windows,
# d'installer_windows.bat). Les mots de passe d'administration (sudo, Mac) sont demandés par le système.
# Relançable : chaque étape déjà faite est sautée. Les mots de passe du warehouse sont générés, jamais
# affichés, et restent dans IDEA/.env.warehouse (lisible par vous seul).
# Compatible bash 3.2 (macOS) : pas de syntaxe propre à bash 4, pas de `timeout`.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
step() { printf '\n== %s\n' "$*"; }
fail() { printf '\nÉCHEC : %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
major() { printf '%s' "$1" | sed -E 's/^[^0-9]*([0-9]+).*/\1/'; }
python_ok() { have python3 && python3 -c 'import sys, ensurepip; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
psql_ok() { have psql && [ "$(major "$(psql --version | awk '{print $3}')")" -ge 16 ]; }
node_ok() { have node && [ "$(major "$(node --version)")" -ge 18 ]; }
docker_ok() { have docker && docker info >/dev/null 2>&1; }
is_wsl() { grep -qi microsoft /proc/version 2>/dev/null; }
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO=sudo; fi
# NEOLAB_INSTALL_TOOLS_ONLY=1 : s'arrêter après l'installation des outils (tests du script).
tools_only() { [ "${NEOLAB_INSTALL_TOOLS_ONLY:-}" = 1 ] || return 0; python_ok && psql_ok && node_ok || fail "outils incomplets"; echo "Python, psql, Node : OK (arrêt demandé après les outils)"; exit 0; }

account=${1:-$(id -un)}
account=$(printf '%s' "$account" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '_' | cut -c1-30)
case "$account" in [a-z]*) ;; *) account="u_$account" ;; esac
case "$account" in warehouse_*|pg_*|neolab) account="${account}_lecture" ;; esac
[ "${#account}" -ge 3 ] || account="${account}_neolab"

step "1/8 Outils (installation de ceux qui manquent)"
os=$(uname -s)
if [ "$os" = Darwin ]; then
    if ! have brew; then
        for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
    fi
    if ! have brew; then
        echo "Installation de Homebrew (le mot de passe du Mac est demandé)…"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
        have brew || fail "Homebrew ne s'est pas installé : voir https://brew.sh, puis relancer."
    fi
    python_ok || brew install python
    node_ok || brew install node
    if ! psql_ok; then brew install libpq && brew link --force libpq; fi
    tools_only
    if ! have docker; then brew install --cask docker; fi
    if ! docker_ok; then
        echo "Démarrage de Docker Desktop (au premier lancement : accepter ses conditions dans sa fenêtre)…"
        open -a Docker || true
        waited=0
        until docker_ok; do
            [ "$waited" -lt 600 ] || fail "Docker Desktop ne répond pas : l'ouvrir (Applications), attendre « running », relancer."
            sleep 5; waited=$((waited + 5))
        done
    fi
elif have apt-get; then
    if ! python_ok || ! have curl || ! have unzip; then
        $SUDO apt-get update -qq
        $SUDO apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates unzip
    fi
    if ! psql_ok; then
        $SUDO apt-get install -y -qq postgresql-common
        $SUDO /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
        $SUDO apt-get install -y -qq postgresql-client-16
    fi
    if ! node_ok; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO bash -
        $SUDO apt-get install -y -qq nodejs
    fi
    tools_only
    if ! docker_ok; then
        if is_wsl; then
            fail "Docker ne répond pas dans Ubuntu : lancer Docker Desktop sous Windows (installer_windows.bat l'installe), vérifier Settings → Resources → WSL integration → Ubuntu, puis relancer."
        fi
        if ! have docker; then
            curl -fsSL https://get.docker.com | $SUDO sh
            $SUDO usermod -aG docker "$(id -un)"
            fail "Docker vient d'être installé : se déconnecter puis se reconnecter (ou redémarrer), puis relancer ce script."
        fi
        $SUDO systemctl start docker 2>/dev/null || true
        docker_ok || fail "Docker ne répond pas : « sudo systemctl start docker », et vérifier que vous êtes dans le groupe docker (« groups »)."
    fi
fi
docker_ok || fail "Docker ne répond pas : lancer Docker Desktop (Windows, macOS) ou « sudo systemctl start docker » (Linux)."
docker compose version >/dev/null 2>&1 || fail "Docker Compose 2 introuvable : mettre Docker à jour."
python_ok || fail "Python 3.10 ou plus (avec venv) introuvable : l'installer (LISEZMOI, partie 1)."
psql_ok || fail "Client PostgreSQL 16 ou plus introuvable : l'installer (LISEZMOI, partie 1)."
node_ok || fail "Node.js 18 ou plus introuvable : l'installer (LISEZMOI, partie 1)."
if have sha256sum; then shacheck() { sha256sum -c "$1"; }; else shacheck() { shasum -a 256 -c "$1"; }; fi
echo "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), $(python3 --version), psql $(psql --version | awk '{print $3}'), Node $(node --version) : OK"

step "2/8 Base de données : recoller les morceaux et vérifier"
sums=$(ls neolab_warehouse_*.dump.sha256 2>/dev/null | head -1)
[ -n "$sums" ] || fail "fichier .dump.sha256 introuvable : lancer ce script depuis le dossier décompressé du premier zip."
dump=${sums%.sha256}
folder=$(basename "$HERE")
if [ ! -f "$dump" ] && [ ! -f "$dump.part1" ]; then
    # The Finder (or Explorer) puts the second zip in another folder ("<dossier> 2", "<zip>_2sur2"...),
    # or it is not unpacked yet: look for the piece, then for the zip, next to this folder and in Downloads.
    piece=$(ls "$HERE"/../*/"$dump.part1" "$HERE"/../*/*/"$dump.part1" 2>/dev/null | head -1 || true)
    if [ -n "$piece" ]; then
        mv "$piece" .
    else
        zip2=$(ls "$HERE"/../"${folder}"_2sur2.zip "$HERE"/../../"${folder}"_2sur2.zip "$HOME"/Downloads/"${folder}"_2sur2.zip \
               "$HOME"/Téléchargements/"${folder}"_2sur2.zip 2>/dev/null | head -1 || true)
        [ -n "$zip2" ] || fail "second zip (${folder}_2sur2.zip) introuvable : le mettre à côté du premier, puis relancer."
        echo "décompression de $(basename "$zip2")"
        (cd "$HERE/.." && unzip -q -o "$zip2" "$folder/$dump.part1") || fail "décompression de $zip2 impossible."
    fi
fi
if [ ! -f "$dump" ]; then
    for part in "$dump.part0" "$dump.part1"; do
        [ -f "$part" ] || fail "morceau $part introuvable : décompresser les deux zips, puis relancer."
    done
    cat "$dump.part0" "$dump.part1" > "$dump.tmp" && mv "$dump.tmp" "$dump"
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
[ -x "$HOME/.local/bin/claude" ] && PATH="$HOME/.local/bin:$PATH"
if ! have claude && ! have codex && [ -t 0 ]; then
    printf '\nAucun assistant IA trouvé (claude, codex). Installer Claude Code maintenant ? [O/n] '
    read -r answer || answer=n
    case "$answer" in
        [nN]*) ;;
        *) curl -fsSL https://claude.ai/install.sh | bash && PATH="$HOME/.local/bin:$PATH" ;;
    esac
fi
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
    printf 'Pour poser une question (la première fois, l’assistant demande de se connecter à son compte) :\n'
    printf '    cd ~/neolab-travail && %s\n' "$first"
else
    printf 'Aucun assistant trouvé (claude, codex). Après en avoir installé un (LISEZMOI, partie 2), relancer ce script.\n'
fi
printf 'GitHub Copilot (VS Code) : dans IDEA, « python scripts/warehouse_connect.py config vscode » (LISEZMOI, partie 4).\n'
printf 'Les fois suivantes : lancer Docker, puis « cd %s && docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d ».\n' "$PWD"
