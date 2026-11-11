#!/usr/bin/env bash
# Installe le warehouse NeoLab avec Docker seulement (macOS, Linux), depuis le dossier du premier zip :
#
#     bash installer.sh
#
# 1. Docker (Docker Desktop sur Mac, installé par Homebrew s'il manque; Docker Engine sur Linux);
# 2. la base recollée et vérifiée (empreinte SHA-256);
# 3. l'image tout-en-un construite (base PostgreSQL, serveur MCP, compte de lecture : docker/allinone);
# 4. le conteneur démarré (première fois : la base s'installe dedans, quelques minutes);
# 5. Claude Code, Codex, VS Code et Claude Desktop branchés : ils lancent le serveur MCP par
#    « docker exec -i neolab-warehouse neolab-mcp ».
# Relançable : chaque étape déjà faite est sautée. Aucun mot de passe affiché.
# Compatible bash 3.2 (macOS).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
step() { printf '\n== %s\n' "$*"; }
fail() { printf '\nÉCHEC : %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
docker_ok() { have docker && docker info >/dev/null 2>&1; }
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO=sudo; fi

folder=$(basename "$HERE")                         # neolab_warehouse_20261108
IMAGE="neolab-warehouse:${folder##*_}"
CONTAINER=neolab-warehouse
VOLUME=neolab_warehouse_data
os=$(uname -s)

step "1/5 Docker"
for d in "$HOME/.docker/bin" /Applications/Docker.app/Contents/Resources/bin /usr/local/bin; do
    have docker || { [ -x "$d/docker" ] && PATH="$d:$PATH"; }
done
if [ "$os" = Darwin ]; then
    if ! have docker && [ ! -d /Applications/Docker.app ]; then
        for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
        have brew || fail "Docker Desktop manquant : l'installer depuis https://www.docker.com/products/docker-desktop/ (choisir Apple silicon ou Intel), puis relancer."
        brew install --cask docker
    fi
    if ! docker_ok; then
        echo "démarrage de Docker Desktop (la première fois : accepter ses conditions dans sa fenêtre)"
        open -a Docker || true
    fi
elif ! have docker; then
    curl -fsSL https://get.docker.com | $SUDO sh
    $SUDO usermod -aG docker "$(id -un)"
fi
# Linux: Docker answers but refuses this user (not yet in the docker group): join it and continue under it.
if ! docker_ok && have docker && docker info 2>&1 | grep -qi "permission denied"; then
    id -nG | tr ' ' '\n' | grep -qx docker || { $SUDO groupadd -f docker; $SUDO usermod -aG docker "$(id -un)"; }
    if [ -z "${NEOLAB_SG:-}" ] && have sg; then
        export NEOLAB_SG=1
        exec sg docker -c "bash $(printf '%q' "$HERE/$(basename "$0")") $(printf '%q ' "$@")"
    fi
fi
[ "$os" = Darwin ] || docker_ok || $SUDO systemctl start docker 2>/dev/null || true
waited=0
until docker_ok; do
    [ "$waited" -lt 600 ] || fail "Docker ne répond pas : lancer Docker Desktop (Mac) ou « sudo systemctl start docker » (Linux), puis relancer."
    [ $((waited % 15)) -eq 0 ] && echo "  attente de Docker : $waited s"
    sleep 5; waited=$((waited + 5))
done
echo "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null) : OK"

step "2/5 Base de données : recoller les morceaux et vérifier"
sums=$(ls neolab_warehouse_*.dump.sha256 2>/dev/null | head -1)
[ -n "$sums" ] || fail "fichier .dump.sha256 introuvable : lancer ce script depuis le dossier décompressé du premier zip."
dump=${sums%.sha256}
if [ ! -f "$dump" ] && [ ! -f "$dump.part1" ]; then
    # The Finder puts the second zip in another folder (« … 2 »), or it is not unpacked yet.
    piece=$(ls "$HERE"/../*/"$dump.part1" "$HERE"/../*/*/"$dump.part1" "$HERE"/../../*/*/"$dump.part1" \
               "$HOME"/Downloads/*/"$dump.part1" "$HOME"/Downloads/*/*/"$dump.part1" 2>/dev/null | head -1 || true)
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
if have sha256sum; then sumcheck="sha256sum -c"; else sumcheck="shasum -a 256 -c"; fi
if ! $sumcheck "$sums"; then
    rm -f "$dump"
    fail "la base est incomplète ou abîmée : retélécharger les deux zips, les décompresser ici, relancer."
fi

step "3/5 Image Docker (la première fois : téléchargements et construction, quelques minutes)"
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "image $IMAGE déjà construite"
else
    [ -d IDEA ] || tar xzf IDEA-code.tar.gz
    printf 'IDEA/data\nIDEA/.git\n*.part*\n*.zip\n*.sha256\n' > .dockerignore
    docker build -t "$IMAGE" -f IDEA/docker/allinone/Dockerfile . || fail "construction de l'image impossible (message ci-dessus)."
fi

step "4/5 Démarrage (la première fois : installation de la base dans le conteneur, 2 à 5 minutes)"
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    docker start "$CONTAINER" >/dev/null
else
    docker run -d --name "$CONTAINER" --restart unless-stopped -v "$VOLUME:/var/lib/postgresql/data" "$IMAGE" >/dev/null
fi
waited=0
until docker exec "$CONTAINER" test -f /var/lib/postgresql/data/neolab/ready 2>/dev/null; do
    if docker logs "$CONTAINER" 2>&1 | grep -q "\[neolab\] ÉCHEC"; then
        docker logs "$CONTAINER" 2>&1 | grep -v "^pg_restore: warning" | tail -25
        fail "l'installation de la base a échoué (messages ci-dessus)."
    fi
    [ "$waited" -lt 1800 ] || fail "la base ne s'installe pas : « docker logs $CONTAINER » pour le détail."
    [ $((waited % 30)) -eq 0 ] && echo "  $(docker logs "$CONTAINER" 2>&1 | grep '^\[neolab\]' | tail -1) ($waited s)"
    sleep 5; waited=$((waited + 5))
done
check=$(docker exec "$CONTAINER" neolab-check 2>&1 || true)
printf '%s\n' "$check" | grep -q "PASS" || { printf '%s\n' "$check" | tail -12; fail "le serveur MCP ne répond pas (message ci-dessus)."; }
echo "base prête, serveur MCP : PASS"

step "5/5 Votre assistant"
mkdir -p "$HOME/neolab-travail"
docker cp "$CONTAINER:/opt/neolab/workspace/." "$HOME/neolab-travail/" >/dev/null
echo "dossier de travail : $HOME/neolab-travail"
[ -x "$HOME/.local/bin/claude" ] && PATH="$HOME/.local/bin:$PATH"
if ! have claude && ! have codex && [ -t 0 ]; then
    printf '\nAucun assistant IA trouvé (claude, codex). Installer Claude Code maintenant ? [O/n] '
    read -r answer || answer=n
    case "$answer" in
        [nN]*) ;;
        *) curl -fsSL https://claude.ai/install.sh | bash && PATH="$HOME/.local/bin:$PATH" ;;
    esac
fi
# Full path: desktop applications (Codex, Claude Desktop) do not get the terminal's PATH (macOS: no /usr/local/bin).
docker_exe=$(command -v docker)
assistants=""
if have claude; then
    claude mcp remove neolab-warehouse -s user >/dev/null 2>&1 || true
    claude mcp add --scope user neolab-warehouse -- "$docker_exe" exec -i "$CONTAINER" neolab-mcp >/dev/null
    assistants="$assistants claude"
    echo "Claude Code : serveur neolab-warehouse enregistré"
fi
if have codex; then
    codex mcp remove neolab-warehouse >/dev/null 2>&1 || true
    codex mcp add neolab-warehouse -- "$docker_exe" exec -i "$CONTAINER" neolab-mcp >/dev/null 2>&1 || true
    assistants="$assistants codex"
fi
if have opencode; then
    # Its own command writes the format of the installed version, in its global configuration.
    if opencode mcp add neolab-warehouse -- "$docker_exe" exec -i "$CONTAINER" neolab-mcp </dev/null >/dev/null 2>&1; then
        echo "OpenCode : serveur neolab-warehouse enregistré"; assistants="$assistants opencode"
    fi
fi
platform=linux; [ "$os" = Darwin ] && platform=darwin
user_opt=""; [ "$os" = Darwin ] || user_opt="--user $(id -u):$(id -g)"
# shellcheck disable=SC2086
docker run --rm $user_opt -e HOME=/tmp -v "$HOME:/h" --entrypoint /opt/neolab/venv/bin/python "$IMAGE" \
    /opt/neolab/IDEA/scripts/warehouse_connect.py register-apps --home /h --platform "$platform" \
    --docker-container "$CONTAINER" --docker-command "$docker_exe" | sed "s#(/h/#($HOME/#"

printf '\nINSTALLATION TERMINÉE.\n\n'
if [ -n "$assistants" ]; then
    printf 'Pour poser une question (la première fois, l’assistant demande de se connecter à son compte) :\n'
    printf '    cd ~/neolab-travail && %s\n' "$(printf '%s' "$assistants" | awk '{print $1}')"
else
    printf 'Aucun assistant en ligne de commande : installer Claude Code ou Codex, puis relancer ce script.\n'
fi
printf 'Codex, VS Code (Copilot) et Claude Desktop : branchés s’ils sont installés (liste ci-dessus) ; les redémarrer.\n'
printf 'Les fois suivantes : lancer Docker Desktop (la base redémarre seule), puis l’assistant.\n'
