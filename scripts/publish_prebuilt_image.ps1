# Publie l'image « avec données » dans le registre privé GitHub (ghcr.io), depuis un PC où l'installation est
# terminée (conteneur neolab-warehouse prêt). Les autres n'auront plus rien à restaurer : docker pull puis run.
#
#   1. Une fois : créer un jeton GitHub (github.com → Settings → Developer settings → Personal access tokens →
#      Tokens (classic) → droits write:packages et read:packages), puis dans PowerShell :
#          docker login ghcr.io -u VOTRE_COMPTE_GITHUB      (coller le jeton comme mot de passe)
#   2. powershell -ExecutionPolicy Bypass -File publish_prebuilt_image.ps1 -Owner VOTRE_COMPTE_GITHUB
#
# Le volume de données n'est que lu; le conteneur est arrêté le temps de la copie (base cohérente), puis
# redémarré. Place disque : environ 2 fois la base (10 à 20 Go) le temps de la fabrication.
# L'image reste privée (choix par défaut de GitHub pour un nouveau paquet) : ne jamais la rendre publique.
param([Parameter(Mandatory = $true)][string]$Owner)
$ErrorActionPreference = 'Continue'
function Fail($text) { Write-Host "`nÉCHEC : $text" -ForegroundColor Red; exit 1 }
$container = 'neolab-warehouse'; $volume = 'neolab_warehouse_data'
$base = (& docker image ls --format '{{.Repository}}:{{.Tag}}' neolab-warehouse | Select-Object -First 1)
if (-not $base) { Fail "image neolab-warehouse introuvable : installer d'abord avec installer_windows.bat." }
$tag = ($base -split ':')[-1]
$target = "ghcr.io/$($Owner.ToLower())/neolab-warehouse:$tag-donnees"
& cmd.exe /c "docker exec $container test -f /var/lib/postgresql/data/neolab/ready >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Fail "la base n'est pas prête : attendre « INSTALLATION TERMINÉE », puis relancer." }

Write-Host "== 1/4 Arrêt de la base (copie cohérente)"
& docker stop $container | Out-Null
Write-Host "== 2/4 Copie de la base dans un conteneur de fabrication (quelques minutes)"
& cmd.exe /c "docker rm -f neolab-bake >nul 2>&1"
& docker run --name neolab-bake --entrypoint sh -v "${volume}:/from:ro" $base -c "mkdir -p /opt/neolab/data && cp -a /from/. /opt/neolab/data/ && rm -f /opt/neolab/data/neolab/attempts"
$copied = $LASTEXITCODE
& docker start $container | Out-Null
if ($copied -ne 0) { & cmd.exe /c "docker rm -f neolab-bake >nul 2>&1"; Fail "copie de la base impossible (place disque ?)." }
Write-Host "== 3/4 Fabrication de l'image $target"
& docker commit `
    --change 'ENV PGDATA=/opt/neolab/data/pgdata' `
    --change 'ENV NEOLAB_STATE=/opt/neolab/data/neolab' `
    --change 'ENTRYPOINT ["neolab-entrypoint"]' `
    --change 'CMD ["postgres", "-c", "logging_collector=on", "-c", "log_destination=csvlog", "-c", "log_filename=postgresql-%Y-%m-%d.log", "-c", "log_rotation_age=1d", "-c", "log_rotation_size=0"]' `
    neolab-bake $target | Out-Null
$made = $LASTEXITCODE
& cmd.exe /c "docker rm neolab-bake >nul 2>&1"
if ($made -ne 0) { Fail "fabrication de l'image impossible." }
Write-Host "== 4/4 Publication (quelques Go : selon la connexion, 5 à 30 minutes)"
& docker push $target
if ($LASTEXITCODE -ne 0) { Fail "publication refusée : vérifier « docker login ghcr.io » et les droits du jeton (write:packages)." }
Write-Host "`nPUBLIÉE : $target (privée)." -ForegroundColor Green
Write-Host "Donner l'accès : github.com → votre profil → Packages → neolab-warehouse → Package settings → Manage access."
Write-Host "Chez les autres : docker login ghcr.io, puis"
Write-Host "  docker run -d --name neolab-warehouse --restart unless-stopped -v neolab_warehouse_data:/opt/neolab/data $target"
