#!/usr/bin/env bash
# Installe le warehouse NeoLab depuis le registre privé GitHub, base déjà installée (macOS, Linux) :
#
#     bash install_from_registry.sh [image] [--replace]
#
# Il faut Docker (Docker Desktop sur Mac), un compte GitHub qui a accès au paquet neolab-warehouse et un jeton
# GitHub classique avec le droit read:packages (demandé une fois par « docker login »). Étapes : Docker,
# téléchargement de l'image (plusieurs Go), conteneur neolab-warehouse, vérification du serveur MCP, branchement
# de Claude Code, Codex, OpenCode, VS Code et Claude Desktop. Relançable. --replace remplace un conteneur
# existant en gardant la base de son volume. Compatible bash 3.2 (macOS).
set -euo pipefail
IMAGE=ghcr.io/tidianecisse777/neolab-warehouse:donnees
REPLACE=0
for arg in "$@"; do case "$arg" in --replace) REPLACE=1 ;; *) IMAGE=$arg ;; esac; done
CONTAINER=neolab-warehouse
VOLUME=neolab_warehouse_donnees
step() { printf '\n== %s\n' "$*"; }
fail() { printf '\nÉCHEC : %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
os=$(uname -s)

step "1/5 Docker"
for d in "$HOME/.docker/bin" /Applications/Docker.app/Contents/Resources/bin /usr/local/bin; do
    have docker || { [ -x "$d/docker" ] && PATH="$d:$PATH"; }
done
have docker || fail "Docker introuvable : installer Docker Desktop (https://www.docker.com/products/docker-desktop/), puis relancer."
if ! docker info >/dev/null 2>&1; then
    [ "$os" = Darwin ] && open -a Docker || true
    waited=0
    until docker info >/dev/null 2>&1; do
        [ "$waited" -lt 600 ] || fail "Docker ne répond pas : lancer Docker Desktop (ou « sudo systemctl start docker »), puis relancer."
        sleep 5; waited=$((waited + 5))
    done
fi
echo "Docker : OK"

step "2/5 Image $IMAGE (la première fois : plusieurs Go, 10 à 60 minutes)"
# A local image (no registry host in its name, e.g. one built here) is used as is.
case "$IMAGE" in */*) pull=1 ;; *) pull=0; docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "image locale $IMAGE introuvable." ;; esac
if [ "$pull" = 1 ] && ! docker pull "$IMAGE"; then
    printf '\nAccès au registre privé GitHub nécessaire (une seule fois).\n'
    printf '  Jeton : github.com > Settings > Developer settings > Personal access tokens > Tokens (classic),\n'
    printf '  droit read:packages. Le coller comme mot de passe ci-dessous (il ne s’affiche pas).\n'
    printf 'Compte GitHub : '; read -r user
    docker login ghcr.io -u "$user" || fail "connexion à ghcr.io refusée : vérifier le compte et le jeton (read:packages)."
    docker pull "$IMAGE" || fail "image inaccessible : demander l'accès au paquet neolab-warehouse à la personne qui l'a publié."
fi

step "3/5 Conteneur $CONTAINER"
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    current=$(docker inspect -f '{{.Config.Image}}' "$CONTAINER")
    if [ "$current" != "$IMAGE" ]; then
        [ "$REPLACE" = 1 ] || fail "un conteneur $CONTAINER existe déjà (image $current) : relancer avec --replace (ses données restent dans leur volume)."
        docker rm -f "$CONTAINER" >/dev/null
    fi
fi
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    docker start "$CONTAINER" >/dev/null
else
    echo "création (la première fois, la base est copiée de l'image dans le volume $VOLUME : quelques minutes)"
    docker run -d --name "$CONTAINER" --restart unless-stopped -v "$VOLUME:/opt/neolab/data" "$IMAGE" >/dev/null \
        || fail "démarrage du conteneur impossible (place disque : environ 25 Go nécessaires)."
fi

step "4/5 Base et serveur MCP"
waited=0
until docker exec "$CONTAINER" sh -c 'test -f $NEOLAB_STATE/ready && pg_isready -q -h 127.0.0.1' >/dev/null 2>&1; do
    [ "$waited" -lt 900 ] || fail "la base ne démarre pas : « docker logs $CONTAINER » pour le détail."
    [ $((waited % 30)) -eq 0 ] && echo "  démarrage de la base… ($waited s)"
    sleep 5; waited=$((waited + 5))
done
check=$(docker exec "$CONTAINER" neolab-check 2>&1 || true)
printf '%s\n' "$check" | grep -q PASS || { printf '%s\n' "$check" | tail -12; fail "le serveur MCP ne répond pas (message ci-dessus)."; }
echo "base prête, serveur MCP : PASS"

step "5/5 Assistants"
mkdir -p "$HOME/neolab-travail"
docker cp "$CONTAINER:/opt/neolab/workspace/." "$HOME/neolab-travail/" >/dev/null
echo "dossier de travail : $HOME/neolab-travail"
[ -x "$HOME/.local/bin/claude" ] && PATH="$HOME/.local/bin:$PATH"
# Full path: desktop applications (Codex, Claude Desktop) do not get the terminal's PATH (macOS: no /usr/local/bin).
docker_exe=$(command -v docker)
assistants=""
if have claude; then
    claude mcp remove neolab-warehouse -s user >/dev/null 2>&1 || true
    claude mcp add --scope user neolab-warehouse -- "$docker_exe" exec -i "$CONTAINER" neolab-mcp >/dev/null
    assistants="$assistants claude"; echo "Claude Code : serveur neolab-warehouse enregistré"
fi
if have codex; then
    codex mcp remove neolab-warehouse >/dev/null 2>&1 || true
    codex mcp add neolab-warehouse -- "$docker_exe" exec -i "$CONTAINER" neolab-mcp >/dev/null 2>&1 || true
    assistants="$assistants codex"
fi
if have opencode; then
    if opencode mcp add neolab-warehouse -- "$docker_exe" exec -i "$CONTAINER" neolab-mcp </dev/null >/dev/null 2>&1; then
        echo "OpenCode : serveur neolab-warehouse enregistré"; assistants="$assistants opencode"
    fi
fi
platform=linux; [ "$os" = Darwin ] && platform=darwin
user_opt=""; [ "$os" = Darwin ] || user_opt="--user $(id -u):$(id -g)"
# The container's code (kept up to date by neolab-update) writes the application configurations, run in a
# throwaway container of the same image with the home folder mounted.
code=$(mktemp -d)
docker cp "$CONTAINER:/opt/neolab/IDEA/scripts/warehouse_connect.py" "$code/warehouse_connect.py" >/dev/null
chmod 644 "$code/warehouse_connect.py"
# shellcheck disable=SC2086
docker run --rm $user_opt -e HOME=/tmp -v "$HOME:/h" -v "$code:/code:ro" --entrypoint /opt/neolab/venv/bin/python "$IMAGE" \
    /code/warehouse_connect.py register-apps --home /h --platform "$platform" \
    --docker-container "$CONTAINER" --docker-command "$docker_exe" | sed "s#(/h/#($HOME/#"
rm -rf "$code"

printf '\nINSTALLATION TERMINÉE.\n'
if [ -n "$assistants" ]; then
    printf 'Poser une question :  cd ~/neolab-travail && %s\n' "$(printf '%s' "$assistants" | awk '{print $1}')"
else
    printf 'Aucun assistant en ligne de commande : installer Claude Code, Codex ou OpenCode, puis relancer ce script.\n'
fi
printf 'VS Code (Copilot) et Claude Desktop : branchés s’ils sont installés; les redémarrer.\n'
