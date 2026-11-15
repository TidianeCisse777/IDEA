#!/usr/bin/env bash
# Met à jour le warehouse NeoLab installé (conteneur neolab-warehouse) sur macOS ou Linux, sans réinstaller :
# code, migrations, vues et fiches du serveur MCP. Les données et les comptes restent.
#
#     bash update_warehouse.sh            (copié dans ~/neolab par l'installation)
#
# Le code vient du petit paquet « code seul » (étiquette :code, quelques Mo) publié à côté de l'image, avec la
# connexion read:packages faite à l'installation : aucun accès au dépôt n'est nécessaire. Jamais de retour en
# arrière : le code publié liste toutes les versions antérieures de sa branche (.neolab_commits).
# Compatible bash 3.2 (macOS).
set -euo pipefail
CODE_IMAGE=${1:-ghcr.io/tidianecisse777/neolab-warehouse:code}
CONTAINER=neolab-warehouse
TMP_CONTAINER=neolab-code-tmp
fail() { printf '\nÉCHEC : %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

for d in "$HOME/.docker/bin" /Applications/Docker.app/Contents/Resources/bin /usr/local/bin; do
    have docker || { [ -x "$d/docker" ] && PATH="$d:$PATH"; }
done
have docker || fail "Docker introuvable : installer le warehouse d'abord."
if ! docker info >/dev/null 2>&1; then
    [ "$(uname -s)" = Darwin ] && open -a Docker || true
    waited=0
    until docker info >/dev/null 2>&1; do
        [ "$waited" -lt 600 ] || fail "Docker ne répond pas : lancer Docker Desktop, puis relancer."
        sleep 5; waited=$((waited + 5))
    done
fi
docker container inspect "$CONTAINER" >/dev/null 2>&1 || fail "conteneur $CONTAINER absent : installer le warehouse d'abord."
docker start "$CONTAINER" >/dev/null
waited=0
until docker exec "$CONTAINER" sh -c 'test -f $NEOLAB_STATE/ready && pg_isready -q -h 127.0.0.1' >/dev/null 2>&1; do
    [ "$waited" -lt 180 ] || fail "la base du conteneur ne répond pas."
    sleep 5; waited=$((waited + 5))
done

if ! docker pull "$CODE_IMAGE" >/dev/null 2>&1; then
    docker image inspect "$CODE_IMAGE" >/dev/null 2>&1 \
        || fail "code inaccessible ($CODE_IMAGE) : vérifier Internet, ou refaire « docker login ghcr.io » avec le jeton read:packages."
    echo "registre injoignable : dernière copie téléchargée du code utilisée."
fi
latest=$(docker image inspect -f '{{index .Config.Labels "neolab.commit"}}' "$CODE_IMAGE")
[[ "$latest" =~ ^[0-9a-f]{40}$ ]] || fail "version du code publié illisible ($latest)."
current=$(docker exec "$CONTAINER" sh -c 'cat /opt/neolab/version 2>/dev/null' || true)
if [ "$current" = "$latest" ]; then echo "Déjà à jour (${latest:0:7})."; exit 0; fi

work=$(mktemp -d)
cleanup() { docker rm -f "$TMP_CONTAINER" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
docker rm -f "$TMP_CONTAINER" >/dev/null 2>&1 || true
docker create --name "$TMP_CONTAINER" "$CODE_IMAGE" >/dev/null
docker cp "$TMP_CONTAINER:/IDEA" "$work/IDEA" >/dev/null
[ -f "$work/IDEA/docker/allinone/neolab-update" ] || fail "code publié incomplet."
if [[ "$current" =~ ^[0-9a-f]{40}$ ]] && ! grep -qx "$current" "$work/IDEA/.neolab_commits"; then
    fail "le code publié (${latest:0:7}) n'est pas plus récent que celui du conteneur (${current:0:7}) : rien n'est changé."
fi
echo "Mise à jour : ${current:0:7} -> ${latest:0:7}"
docker cp "$work/IDEA/." "$CONTAINER:/opt/neolab/IDEA/" >/dev/null
echo "Application dans le conteneur (1 à 3 minutes)…"
if ! docker exec "$CONTAINER" bash /opt/neolab/IDEA/docker/allinone/neolab-update "$latest" >"$work/maj.log" 2>&1; then
    tail -25 "$work/maj.log"
    fail "mise à jour refusée par le conteneur (message ci-dessus)."
fi
mkdir -p "$HOME/neolab-travail"
docker cp "$CONTAINER:/opt/neolab/workspace/." "$HOME/neolab-travail/" >/dev/null
# Replace this script by the new one (mv: the running bash keeps reading the old file).
self="${BASH_SOURCE[0]}"
if [ -f "$work/IDEA/scripts/update_warehouse.sh" ] && [ -w "$(dirname "$self")" ]; then
    cp "$work/IDEA/scripts/update_warehouse.sh" "$self.new" && mv "$self.new" "$self"
fi
echo "À JOUR (${latest:0:7}). Rouvrir une nouvelle conversation dans l'assistant."
