# Installe le warehouse NeoLab sous Windows 10 ou 11 avec Docker Desktop seulement (pas d'Ubuntu à installer).
# Livré comme installer_windows.ps1, lancé par un double-clic sur installer_windows.bat, depuis le dossier
# décompressé du premier zip :
#   1. Docker Desktop (installé par winget s'il manque), démarré;
#   2. la base recollée (second zip retrouvé) et vérifiée (SHA-256);
#   3. l'image tout-en-un construite (docker/allinone : base PostgreSQL, serveur MCP, compte de lecture);
#   4. le conteneur démarré (première fois : la base s'installe dedans, quelques minutes);
#   5. Claude Code, Codex, VS Code et Claude Desktop branchés : « docker exec -i neolab-warehouse neolab-mcp ».
# Relançable : chaque étape déjà faite est sautée. Aucun mot de passe affiché.
# Continue : sous Windows PowerShell 5.1, un programme qui écrit sur stderr (docker, wsl) deviendrait une erreur
# fatale; chaque étape vérifie son propre résultat ($LASTEXITCODE).
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nÉCHEC : $text" -ForegroundColor Red; exit 1 }
function Quiet($command) { & cmd.exe /c "$command >nul 2>&1"; return ($LASTEXITCODE -eq 0) }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$folder = Split-Path -Leaf $here                      # neolab_warehouse_20261108
$image = 'neolab-warehouse:' + ($folder -split '_')[-1]
$container = 'neolab-warehouse'
$volume = 'neolab_warehouse_data'
Set-Location $here

Step "1/5 Docker Desktop"
# Docker Desktop is not always under Program Files (per-user install, other drive).
$candidates = @((Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
                (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
                (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\Docker Desktop.exe'),
                (Join-Path $env:LOCALAPPDATA 'Docker\Docker Desktop.exe'))
$cli = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($cli) { $candidates += (Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $cli.Source))) 'Docker Desktop.exe') }
$reg = Get-ItemProperty 'HKLM:\SOFTWARE\Docker Inc.\Docker\1.0', 'HKCU:\SOFTWARE\Docker Inc.\Docker\1.0' -ErrorAction SilentlyContinue |
       Where-Object { $_.AppPath } | Select-Object -First 1
if ($reg) { $candidates += (Join-Path $reg.AppPath 'Docker Desktop.exe') }
$dockerApp = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $dockerApp) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "Docker Desktop manquant : l'installer depuis https://www.docker.com/products/docker-desktop/ puis relancer installer_windows.bat."
    }
    Write-Host "Installation de Docker Desktop (quelques minutes; Windows peut demander l'autorisation)…"
    & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    $dockerApp = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $dockerApp) { Fail "Docker Desktop installé : redémarrer l'ordinateur si Windows le demande, puis relancer installer_windows.bat." }
}
Write-Host "Docker Desktop : $dockerApp"
# The docker command sits next to Docker Desktop (resources\bin); a fresh install is not yet on PATH.
$bin = Join-Path (Split-Path -Parent $dockerApp) 'resources\bin'
if ((Test-Path $bin) -and -not (Get-Command docker.exe -ErrorAction SilentlyContinue)) { $env:Path = "$bin;$env:Path" }
if (-not (Quiet 'docker info')) {
    if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        Write-Host "Démarrage de Docker Desktop (la première fois : accepter ses conditions dans sa fenêtre)…"
        Start-Process $dockerApp
    }
    $waited = 0
    while (-not (Quiet 'docker info')) {
        if ($waited -ge 600) {
            Fail "Docker ne répond pas : ouvrir Docker Desktop et attendre « Engine running ». S'il signale WSL, taper « wsl --update » dans PowerShell (administrateur), redémarrer, puis relancer."
        }
        if ($waited % 15 -eq 0) { Write-Host "  attente de Docker : $waited s" }
        Start-Sleep -Seconds 5; $waited += 5
    }
}
Write-Host "Docker répond : OK"

Step "2/5 Base de données : recoller les morceaux et vérifier"
$sums = Get-ChildItem -Path $here -Filter 'neolab_warehouse_*.dump.sha256' | Select-Object -First 1
if (-not $sums) { Fail "fichier .dump.sha256 introuvable : lancer installer_windows.bat depuis le dossier décompressé du premier zip." }
$dump = $sums.Name -replace '\.sha256$', ''
$part0 = Join-Path $here "$dump.part0"; $part1 = Join-Path $here "$dump.part1"; $dumpPath = Join-Path $here $dump
if (-not (Test-Path $part1) -and -not (Test-Path $dumpPath)) {
    # « Extraire tout » met chaque zip dans son propre dossier : chercher le morceau, puis le second zip.
    $piece = Get-ChildItem -Path (Split-Path -Parent $here), (Join-Path $env:USERPROFILE 'Downloads') -Recurse -Depth 3 `
                 -Filter "$dump.part1" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($piece) {
        Move-Item $piece.FullName $part1 -ErrorAction Stop
    } else {
        $parent = Split-Path -Parent $here
        $zip2 = @((Join-Path $parent "${folder}_2sur2.zip"), (Join-Path (Split-Path -Parent $parent) "${folder}_2sur2.zip"),
                  (Join-Path $env:USERPROFILE "Downloads\${folder}_2sur2.zip")) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $zip2) { Fail "second zip (${folder}_2sur2.zip) introuvable : le mettre dans Téléchargements, puis relancer." }
        Write-Host "Décompression de $(Split-Path -Leaf $zip2)…"
        $tmp = Join-Path $env:TEMP 'neolab_zip2'
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction Stop }
        Expand-Archive -Path $zip2 -DestinationPath $tmp -ErrorAction Stop
        Move-Item (Join-Path $tmp "$folder\$dump.part1") $part1 -ErrorAction Stop
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
if (-not (Test-Path $dumpPath)) {
    foreach ($part in $part0, $part1) { if (-not (Test-Path $part)) { Fail "morceau $part introuvable : décompresser les deux zips, puis relancer." } }
    $out = [System.IO.File]::Create("$dumpPath.tmp")
    foreach ($part in $part0, $part1) { $in = [System.IO.File]::OpenRead($part); $in.CopyTo($out); $in.Close() }
    $out.Close()
    Move-Item "$dumpPath.tmp" $dumpPath -Force -ErrorAction Stop
}
$expected = ((Get-Content $sums.FullName -Raw) -split '\s+')[0].ToLower()
$actual = (Get-FileHash $dumpPath -Algorithm SHA256).Hash.ToLower()
if ($expected -ne $actual) {
    Remove-Item $dumpPath -Force
    Fail "la base est incomplète ou abîmée : retélécharger les deux zips, les décompresser ici, relancer."
}
Write-Host "base vérifiée : OK"

Step "3/5 Image Docker (la première fois : téléchargements et construction, quelques minutes)"
if (Quiet "docker image inspect $image") {
    Write-Host "image $image déjà construite"
} else {
    if (-not (Test-Path (Join-Path $here 'IDEA'))) {
        & tar.exe -xzf IDEA-code.tar.gz
        if ($LASTEXITCODE -ne 0) { Fail "décompression du code impossible (IDEA-code.tar.gz)." }
    }
    [System.IO.File]::WriteAllText((Join-Path $here '.dockerignore'), "IDEA/data`nIDEA/.git`n*.part*`n*.zip`n*.sha256`n")
    & cmd.exe /c "docker build -t $image -f IDEA/docker/allinone/Dockerfile . 2>&1"
    if ($LASTEXITCODE -ne 0) { Fail "construction de l'image impossible (message ci-dessus)." }
}

Step "4/5 Démarrage (la première fois : installation de la base dans le conteneur, 2 à 5 minutes)"
if (Quiet "docker container inspect $container") {
    Quiet "docker start $container" | Out-Null
} else {
    & cmd.exe /c "docker run -d --name $container --restart unless-stopped -v ${volume}:/var/lib/postgresql/data $image >nul"
    if ($LASTEXITCODE -ne 0) { Fail "démarrage du conteneur impossible." }
}
$waited = 0
while (-not (Quiet "docker exec $container test -f /var/lib/postgresql/data/neolab/ready")) {
    $logs = (& cmd.exe /c "docker logs $container 2>&1") -join "`n"
    if ($logs -match '\[neolab\] ÉCHEC') {
        ($logs -split "`n" | Where-Object { $_ -notmatch '^pg_restore: warning' } | Select-Object -Last 25) -join "`n" | Write-Host
        Fail "l'installation de la base a échoué (messages ci-dessus)."
    }
    if ($waited -ge 1800) { Fail "la base ne s'installe pas : « docker logs $container » pour le détail." }
    if ($waited % 30 -eq 0) {
        $last = ($logs -split "`n" | Where-Object { $_ -match '^\[neolab\]' } | Select-Object -Last 1)
        Write-Host "  $last ($waited s)"
    }
    Start-Sleep -Seconds 5; $waited += 5
}
$check = (& cmd.exe /c "docker exec $container neolab-check 2>&1") -join "`n"
if ($check -notmatch 'PASS') { Write-Host $check; Fail "le serveur MCP ne répond pas (message ci-dessus)." }
Write-Host "base prête, serveur MCP : PASS"

Step "5/5 Votre assistant"
$work = Join-Path $env:USERPROFILE 'neolab-travail'
New-Item -ItemType Directory -Force $work | Out-Null
Quiet "docker cp ${container}:/opt/neolab/workspace/. `"$work`"" | Out-Null
Write-Host "dossier de travail : $work"
$claudeLocal = Join-Path $env:USERPROFILE '.local\bin'
if (Test-Path (Join-Path $claudeLocal 'claude.exe')) { $env:Path = "$claudeLocal;$env:Path" }
$hasClaude = [bool](Get-Command claude -ErrorAction SilentlyContinue)
$hasCodex = [bool](Get-Command codex -ErrorAction SilentlyContinue)
if (-not $hasClaude -and -not $hasCodex) {
    $answer = Read-Host "Aucun assistant IA trouvé (claude, codex). Installer Claude Code maintenant ? [O/n]"
    if ($answer -notmatch '^[nN]') {
        Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
        $env:Path = "$claudeLocal;$env:Path"
        $hasClaude = [bool](Get-Command claude -ErrorAction SilentlyContinue)
    }
}
# Full path: applications started from the Start menu (Codex, Claude Desktop) may not find a bare "docker".
$dockerExe = (Get-Command docker.exe -ErrorAction SilentlyContinue).Source
if (-not $dockerExe) { $dockerExe = 'docker' }
$server = "`"$dockerExe`" exec -i $container neolab-mcp"
if ($hasClaude) {
    Quiet "claude mcp remove neolab-warehouse -s user" | Out-Null
    if (Quiet "claude mcp add --scope user neolab-warehouse -- $server") { Write-Host "Claude Code : serveur neolab-warehouse enregistré" }
    else { Write-Host "Claude Code : enregistrement impossible; à la main : claude mcp add --scope user neolab-warehouse -- $server" -ForegroundColor Yellow }
}
if ($hasCodex) {
    Quiet "codex mcp remove neolab-warehouse" | Out-Null
    Quiet "codex mcp add neolab-warehouse -- $server" | Out-Null
}
if (Get-Command opencode -ErrorAction SilentlyContinue) {
    # Its own command writes the format of the installed version, in its global configuration.
    if (Quiet "opencode mcp add neolab-warehouse -- $server <nul") { Write-Host "OpenCode : serveur neolab-warehouse enregistré" }
}
# Codex (config.toml), VS Code (Copilot) and Claude Desktop, if installed: written from a throwaway container
# with the Windows profile mounted, by the same tested code as on Mac and Linux.
& cmd.exe /c "docker run --rm -e HOME=/tmp -v `"$($env:USERPROFILE):/h`" --entrypoint /opt/neolab/venv/bin/python $image /opt/neolab/IDEA/scripts/warehouse_connect.py register-apps --home /h --platform windows --docker-container $container --docker-command `"$dockerExe`" 2>&1"

Write-Host "`nINSTALLATION TERMINÉE." -ForegroundColor Green
if ($hasClaude -or $hasCodex) {
    $tool = if ($hasClaude) { 'claude' } else { 'codex' }
    Write-Host "Pour poser une question : ouvrir PowerShell, puis  cd `"$work`"; $tool"
    Write-Host "(la première fois, l'assistant demande de se connecter à son compte et d'autoriser neolab-warehouse)."
} else {
    Write-Host "Aucun assistant en ligne de commande : installer Claude Code ou Codex, puis relancer installer_windows.bat."
}
Write-Host "Codex (application), VS Code (Copilot) et Claude Desktop : branchés s'ils sont installés (liste ci-dessus); les redémarrer."
Write-Host "Les fois suivantes : lancer Docker Desktop (la base redémarre seule), puis l'assistant."
