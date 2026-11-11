# Installe le warehouse NeoLab depuis le registre privé GitHub, base déjà installée : rien à restaurer.
# Double-cliquer install_from_registry_windows.bat, ou :
#
#     powershell -ExecutionPolicy Bypass -File install_from_registry_windows.ps1 [-Image ghcr.io/…:donnees] [-Replace] [-NewData]
#
# -Replace : remplace un conteneur existant par l'image demandée en gardant la base du volume (nouveau code).
# -NewData : supprime aussi le volume de la base pour prendre celle de l'image (nouvelles données; demande confirmation).
#
# Il faut Docker Desktop, un compte GitHub qui a accès au paquet neolab-warehouse, et un jeton GitHub classique
# avec le droit read:packages (demandé une seule fois par « docker login »). Étapes : Docker, téléchargement de
# l'image (plusieurs Go), démarrage du conteneur neolab-warehouse, vérification du serveur MCP, puis
# branchement des assistants (Claude Code, Codex, OpenCode, VS Code, Claude Desktop) par le script fourni
# dans l'image. Relançable. Aucun mot de passe affiché.
param([string]$Image = 'ghcr.io/tidianecisse777/neolab-warehouse:donnees', [switch]$Replace, [switch]$NewData)
$ErrorActionPreference = 'Continue'
$container = 'neolab-warehouse'
$volume = 'neolab_warehouse_donnees'
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nÉCHEC : $text" -ForegroundColor Red; exit 1 }

Step "1/5 Docker"
$docker = (Get-Command docker.exe -ErrorAction SilentlyContinue).Source
if (-not $docker) {
    $docker = @("$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
                "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $docker) { Fail "Docker Desktop introuvable : l'installer depuis https://www.docker.com/products/docker-desktop/, puis relancer." }
$env:Path = "$(Split-Path -Parent $docker);$env:Path"
& $docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $app = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $docker))) 'Docker Desktop.exe'
    if (Test-Path $app) { Write-Host "démarrage de Docker Desktop…"; Start-Process $app }
    $waited = 0
    do { Start-Sleep -Seconds 5; $waited += 5; & $docker info *> $null } while ($LASTEXITCODE -ne 0 -and $waited -lt 600)
    if ($LASTEXITCODE -ne 0) { Fail "Docker ne répond pas : ouvrir Docker Desktop, attendre « Engine running », relancer." }
}
Write-Host "Docker : OK"

Step "2/5 Image $Image (la première fois : plusieurs Go, 10 à 60 minutes)"
& $docker pull $Image
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nAccès au registre privé GitHub nécessaire (une seule fois)." -ForegroundColor Yellow
    Write-Host "  Jeton : github.com > Settings > Developer settings > Personal access tokens > Tokens (classic),"
    Write-Host "  droit read:packages. Le coller comme mot de passe ci-dessous (il ne s'affiche pas)."
    $user = Read-Host "Compte GitHub"
    & $docker login ghcr.io -u $user
    if ($LASTEXITCODE -ne 0) { Fail "connexion à ghcr.io refusée : vérifier le compte et le jeton (read:packages)." }
    & $docker pull $Image
    if ($LASTEXITCODE -ne 0) { Fail "image inaccessible : demander l'accès au paquet neolab-warehouse à la personne qui l'a publié." }
}

Step "3/5 Conteneur $container"
& $docker container inspect $container *> $null
if ($LASTEXITCODE -eq 0) {
    $current = ((& $docker inspect -f '{{.Config.Image}}' $container) | Out-String).Trim()
    if ($current -ne $Image) {
        if (-not $Replace) {
            Fail "un conteneur $container existe déjà (image $current). Relancer avec -Replace pour le remplacer (ses données restent dans leur volume)."
        }
        & $docker rm -f $container | Out-Null
    }
}
if ($NewData) {
    & $docker container inspect $container *> $null
    if ($LASTEXITCODE -eq 0) { & $docker rm -f $container | Out-Null }
    $answer = Read-Host "Supprimer la base locale (volume $volume) pour prendre celle de l'image ? [o/N]"
    if ($answer -notmatch '^[oOyY]') { Fail "rien supprimé." }
    & $docker volume rm $volume *> $null
}
& $docker container inspect $container *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "création (la première fois, la base est copiée de l'image dans le volume $volume : quelques minutes)"
    & $docker run -d --name $container --restart unless-stopped -v "${volume}:/opt/neolab/data" $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "démarrage du conteneur impossible (place disque : environ 25 Go nécessaires)." }
} else {
    & $docker start $container | Out-Null
}

Step "4/5 Base et serveur MCP"
$waited = 0
do {
    & $docker exec $container sh -c 'test -f $NEOLAB_STATE/ready && pg_isready -q -h 127.0.0.1' *> $null
    if ($LASTEXITCODE -eq 0) { break }
    if ($waited % 30 -eq 0) { Write-Host "  démarrage de la base… ($waited s)" }
    Start-Sleep -Seconds 5; $waited += 5
} while ($waited -lt 900)
if ($LASTEXITCODE -ne 0) { Fail "la base ne démarre pas : « docker logs $container » pour le détail." }
$check = (& $docker exec $container neolab-check 2>&1) -join "`n"
if ($check -notmatch 'PASS') { Write-Host $check; Fail "le serveur MCP ne répond pas (message ci-dessus)." }
Write-Host "base prête, serveur MCP : PASS"

Step "5/5 Assistants et mise à jour"
$tools = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'neolab'
New-Item -ItemType Directory -Force $tools | Out-Null
foreach ($name in 'connect_assistants_windows.ps1', 'connect_assistants_windows.bat', 'update_warehouse_windows.ps1', 'update_warehouse_windows.bat') {
    & $docker cp "${container}:/opt/neolab/IDEA/scripts/$name" (Join-Path $tools $name) *> $null
}
$connect = Join-Path $tools 'connect_assistants_windows.ps1'
if (-not (Test-Path $connect)) { Fail "script de branchement absent de l'image : demander une image plus récente." }
& powershell -NoProfile -ExecutionPolicy Bypass -File $connect
Write-Host "`nINSTALLATION TERMINÉE." -ForegroundColor Green
Write-Host "Poser une question : ouvrir PowerShell, puis  cd `$HOME\neolab-travail  et  claude  (ou codex, opencode)."
Write-Host "Scripts copiés dans $tools : connect_assistants_windows.bat (rebrancher), update_warehouse_windows.bat (mettre à jour)."
