# Publie l'image « avec données » dans le registre privé GitHub (ghcr.io), depuis un PC où le warehouse est
# installé et à jour (conteneur neolab-warehouse prêt). Les collègues n'ont plus rien à restaurer :
# install_from_registry_windows.bat (ou install_from_registry.sh) télécharge l'image et la démarre.
#
#   1. Une fois : jeton GitHub classique (github.com → Settings → Developer settings → Personal access tokens →
#      Tokens (classic) → droits write:packages et read:packages), puis dans PowerShell :
#          docker login ghcr.io -u VOTRE_COMPTE_GITHUB      (coller le jeton comme mot de passe)
#   2. powershell -ExecutionPolicy Bypass -File publish_prebuilt_image.ps1 -Owner VOTRE_COMPTE_GITHUB
#
# L'image part du conteneur tel qu'il est (code mis à jour, fiches, documents) et de sa base, copiée pendant
# que le conteneur est arrêté (base cohérente), puis il est redémarré. Place disque : environ 2 fois la base
# (8,6 Go en novembre 2026), le temps de la fabrication. Publiée sous deux étiquettes : <date>-donnees et
# donnees (la dernière). L'image reste privée (choix par défaut de GitHub) : ne jamais la rendre publique, elle
# contient des projets privés et les mots de passe internes du conteneur (communs à toutes les copies; la base
# n'est pas ouverte hors du conteneur).
param([Parameter(Mandatory = $true)][string]$Owner)
$ErrorActionPreference = 'Continue'
function Fail($text) { Write-Host "`nÉCHEC : $text" -ForegroundColor Red; exit 1 }
$container = 'neolab-warehouse'
$stamp = Get-Date -Format 'yyyyMMdd'
$repo = "ghcr.io/$($Owner.ToLower())/neolab-warehouse"
$target = "$repo`:$stamp-donnees"
$latest = "$repo`:donnees"

& docker container inspect $container *> $null
if ($LASTEXITCODE -ne 0) { Fail "conteneur $container absent : installer le warehouse d'abord." }
$state = ((& docker exec $container sh -c 'echo $NEOLAB_STATE') | Out-String).Trim()
$pgdata = ((& docker exec $container sh -c 'echo $PGDATA') | Out-String).Trim()
& docker exec $container sh -c 'test -f $NEOLAB_STATE/ready' *> $null
if ($LASTEXITCODE -ne 0 -or -not $state -or -not $pgdata) { Fail "la base n'est pas prête : attendre la fin de l'installation, puis relancer." }
$dataRoot = Split-Path -Parent $pgdata
if ($dataRoot -ne '/var/lib/postgresql/data') {
    # A container started from a published image already carries a copy of the data in its image layers:
    # baking it again would store the base twice. Publish from the PC installed with the zips.
    Fail "ce conteneur vient déjà d'une image publiée : publier depuis le PC installé avec les zips."
}
$mounts = ((& docker inspect -f '{{json .Mounts}}' $container) | Out-String) | ConvertFrom-Json
$volume = ($mounts | Where-Object { $_.Destination -eq $dataRoot } | Select-Object -First 1).Name
if (-not $volume) { Fail "volume de données du conteneur introuvable." }
$version = ((& docker exec $container sh -c 'cat /opt/neolab/version 2>/dev/null') | Out-String).Trim()
Write-Host "Base : volume $volume; code : $(if ($version) { $version } else { 'version d''installation' })"

Write-Host "== 1/5 Arrêt de la base (copie cohérente)"
& docker stop $container | Out-Null
Write-Host "== 2/5 Instantané du conteneur (code et réglages à jour, sans la base)"
& docker commit $container neolab-snapshot:tmp | Out-Null
if ($LASTEXITCODE -ne 0) { & docker start $container | Out-Null; Fail "instantané impossible (place disque ?)." }
Write-Host "== 3/5 Copie de la base dans l'image (quelques minutes)"
& cmd.exe /c "docker rm -f neolab-bake >nul 2>&1"
# /opt/neolab/data is outside any declared VOLUME: the copy becomes part of the image, and Docker copies it into
# the colleague's new named volume at first start.
& docker run --name neolab-bake --entrypoint sh -v "${volume}:/from:ro" neolab-snapshot:tmp -c "mkdir -p /opt/neolab/data && cp -a /from/. /opt/neolab/data/ && rm -f /opt/neolab/data/neolab/attempts && test -f /opt/neolab/data/neolab/ready && test -f /opt/neolab/data/pgdata/PG_VERSION"
$copied = $LASTEXITCODE
& docker start $container | Out-Null
if ($copied -ne 0) { & cmd.exe /c "docker rm -f neolab-bake >nul 2>&1 & docker rmi neolab-snapshot:tmp >nul 2>&1"; Fail "copie de la base impossible (place disque ?)." }
Write-Host "== 4/5 Fabrication de l'image $target"
& docker commit `
    --change 'ENV PGDATA=/opt/neolab/data/pgdata' `
    --change 'ENV NEOLAB_STATE=/opt/neolab/data/neolab' `
    --change 'ENTRYPOINT ["neolab-entrypoint"]' `
    --change 'CMD ["postgres", "-c", "logging_collector=on", "-c", "log_destination=csvlog", "-c", "log_filename=postgresql-%Y-%m-%d.log", "-c", "log_rotation_age=1d", "-c", "log_rotation_size=0"]' `
    neolab-bake $target | Out-Null
$made = $LASTEXITCODE
& cmd.exe /c "docker rm neolab-bake >nul 2>&1 & docker rmi neolab-snapshot:tmp >nul 2>&1"
if ($made -ne 0) { Fail "fabrication de l'image impossible." }
& docker tag $target $latest
Write-Host "== 5/5 Publication (plusieurs Go : 10 à 60 minutes selon la connexion)"
& docker push $target
if ($LASTEXITCODE -ne 0) { Fail "publication refusée : vérifier « docker login ghcr.io » et les droits du jeton (write:packages)." }
& docker push $latest | Out-Null
Write-Host "`nPUBLIÉE : $target et $latest (privées)." -ForegroundColor Green
Write-Host "Donner l'accès : github.com → votre profil → Packages → neolab-warehouse → Package settings → Manage access."
Write-Host "Chez un collègue : install_from_registry_windows.bat (Windows) ou bash install_from_registry.sh (Mac, Linux)."
