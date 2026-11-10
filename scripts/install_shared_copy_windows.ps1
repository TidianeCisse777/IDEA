# Installe la copie partagée du warehouse NeoLab sous Windows 10 ou 11, livré comme installer_windows.ps1
# et lancé par un double-clic sur installer_windows.bat :
#   1. Ubuntu (WSL) s'il manque (redémarrage demandé une fois, puis relancer installer_windows.bat);
#   2. Docker Desktop s'il manque (winget), démarré et relié à Ubuntu;
#   3. le second zip retrouvé et décompressé à côté du premier;
#   4. le dossier copié dans Ubuntu, puis installer.sh y fait le reste (outils Linux, base, compte, assistant).
# Relançable : chaque étape déjà faite est sautée.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nÉCHEC : $text" -ForegroundColor Red; exit 1 }
function IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Elevate {
    Write-Host "Droits d'administrateur nécessaires : Windows va demander l'autorisation."
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSCommandPath`""
    exit 0
}
function Distros {
    # wsl.exe writes its own lists in UTF-16: drop the NUL bytes.
    $raw = & wsl.exe -l -q 2>$null
    if (-not $raw) { return @() }
    return @($raw | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$folder = Split-Path -Leaf $here

Step "1/4 Ubuntu (WSL)"
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { Fail "WSL indisponible : Windows 10 version 2004 ou plus récent requis." }
$ubuntu = Distros | Where-Object { $_ -like 'Ubuntu*' } | Select-Object -First 1
if (-not $ubuntu) {
    if (-not (IsAdmin)) { Elevate }
    Write-Host "Installation d'Ubuntu (WSL)…"
    & wsl.exe --install -d Ubuntu
    Write-Host "`nUbuntu est installé. 1) Redémarrer l'ordinateur. 2) Ouvrir « Ubuntu » depuis le menu Démarrer et choisir"
    Write-Host "un nom d'utilisateur et un mot de passe Linux (à retenir). 3) Relancer installer_windows.bat." -ForegroundColor Yellow
    exit 0
}
& wsl.exe --set-default $ubuntu | Out-Null
$linuxUser = (& wsl.exe -d $ubuntu -- id -un).Trim()
if (-not $linuxUser) { Fail "Ubuntu ne répond pas : l'ouvrir une fois depuis le menu Démarrer, puis relancer." }
Write-Host "$ubuntu, utilisateur Linux $linuxUser : OK"

Step "2/4 Docker Desktop"
$dockerApp = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if (-not (Test-Path $dockerApp)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "Docker Desktop manquant et winget indisponible : l'installer depuis https://www.docker.com/products/docker-desktop/ puis relancer."
    }
    Write-Host "Installation de Docker Desktop (quelques minutes; Windows peut demander l'autorisation)…"
    & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    if (-not (Test-Path $dockerApp)) { Fail "Docker Desktop ne s'est pas installé : l'installer à la main, puis relancer." }
    Write-Host "Docker Desktop installé. Si Windows demande de redémarrer, redémarrer puis relancer installer_windows.bat." -ForegroundColor Yellow
}
function DockerInUbuntu { & wsl.exe -d $ubuntu -- docker info *> $null; return ($LASTEXITCODE -eq 0) }
if (-not (DockerInUbuntu)) {
    if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        Write-Host "Démarrage de Docker Desktop (au premier lancement : accepter ses conditions dans sa fenêtre)…"
        Start-Process $dockerApp
    }
    $waited = 0
    while (-not (DockerInUbuntu)) {
        if ($waited -ge 600) {
            Fail "Docker ne répond pas dans Ubuntu : dans Docker Desktop, Settings → Resources → WSL integration → activer $ubuntu → Apply, puis relancer."
        }
        Start-Sleep -Seconds 5; $waited += 5
    }
}
Write-Host "Docker répond dans $ubuntu : OK"

Step "3/4 Les deux zips"
$sums = Get-ChildItem -Path $here -Filter 'neolab_warehouse_*.dump.sha256' | Select-Object -First 1
if (-not $sums) { Fail "fichier .dump.sha256 introuvable : lancer installer_windows.bat depuis le dossier décompressé du premier zip." }
$dump = $sums.Name -replace '\.sha256$', ''
if (-not (Test-Path (Join-Path $here "$dump.part1")) -and -not (Test-Path (Join-Path $here $dump))) {
    # « Extraire tout » met chaque zip dans son propre dossier : chercher le morceau, puis le second zip.
    $piece = Get-ChildItem -Path (Split-Path -Parent $here), (Join-Path $env:USERPROFILE 'Downloads') -Recurse -Depth 3 `
                 -Filter "$dump.part1" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($piece) {
        Move-Item $piece.FullName (Join-Path $here "$dump.part1")
    } else {
        $parent = Split-Path -Parent $here
        $candidates = @((Join-Path $parent "${folder}_2sur2.zip"), (Join-Path (Split-Path -Parent $parent) "${folder}_2sur2.zip"),
                        (Join-Path $env:USERPROFILE "Downloads\${folder}_2sur2.zip"))
        $zip2 = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $zip2) { Fail "second zip (${folder}_2sur2.zip) introuvable : le mettre dans Téléchargements, puis relancer." }
        Write-Host "Décompression de $(Split-Path -Leaf $zip2)…"
        $tmp = Join-Path $env:TEMP "neolab_zip2"
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        Expand-Archive -Path $zip2 -DestinationPath $tmp
        Move-Item (Join-Path $tmp "$folder\$dump.part1") (Join-Path $here "$dump.part1")
        Remove-Item $tmp -Recurse -Force
    }
}
Write-Host "les deux morceaux de la base sont là : OK"

Step "4/4 Installation dans Ubuntu (le mot de passe Linux peut être demandé)"
$source = (& wsl.exe -d $ubuntu -- wslpath -a ($here -replace '\\', '/')).Trim()
$command = "mkdir -p ~/neolab && cp -ru '$source' ~/neolab/ && cd ~/neolab/'$folder' && bash installer.sh"
& wsl.exe -d $ubuntu -- bash -lc $command
if ($LASTEXITCODE -ne 0) { Fail "l'installation dans Ubuntu s'est arrêtée (message ci-dessus) : corriger, puis relancer installer_windows.bat." }
# Applications Windows (Codex, VS Code/Copilot, Claude Desktop) : serveur lancé dans Ubuntu par wsl.exe.
$winHome = (& wsl.exe -d $ubuntu -- wslpath -a ($env:USERPROFILE -replace '\\', '/')).Trim()
$register = "cd ~/neolab/'$folder'/IDEA && .venv/bin/python scripts/warehouse_connect.py register-apps --windows-home '$winHome' --wsl-distro '$ubuntu'"
& wsl.exe -d $ubuntu -- bash -lc $register
Write-Host "`nPour poser une question : ouvrir « Ubuntu » depuis le menu Démarrer, puis taper  cd ~/neolab-travail && claude" -ForegroundColor Green
Write-Host "(ou codex). Codex, VS Code (Copilot) ou Claude Desktop installés sous Windows : les redémarrer, le serveur neolab-warehouse y est ajouté."
