# Met à jour le warehouse NeoLab installé (conteneur neolab-warehouse) avec le dernier code du dépôt GitHub,
# sans réinstaller : code, migrations, vues et fiches du serveur MCP. Les données et les comptes restent.
# Double-cliquer mettre_a_jour_windows.bat, ou :
#
#     powershell -ExecutionPolicy Bypass -File mettre_a_jour_windows.ps1            # mise à jour maintenant
#     powershell -ExecutionPolicy Bypass -File mettre_a_jour_windows.ps1 -Auto      # + à chaque ouverture de session
#     powershell -ExecutionPolicy Bypass -File mettre_a_jour_windows.ps1 -NoAuto    # retirer l'automatique
#
# Dépôt privé : un jeton GitHub en lecture seule (fine-grained, « Contents: Read-only » sur ce dépôt) est
# demandé une fois, puis gardé chiffré pour cet utilisateur Windows (DPAPI) dans %LOCALAPPDATA%\neolab.
param([switch]$Auto, [switch]$NoAuto, [switch]$Quiet,
      [string]$Repo = 'TidianeCisse777/IDEA', [string]$Branch = 'work/warehouse-fair')
$ErrorActionPreference = 'Continue'
$container = 'neolab-warehouse'
$state = Join-Path $env:LOCALAPPDATA 'neolab'
New-Item -ItemType Directory -Force $state | Out-Null
$log = Join-Path $state 'mise_a_jour.log'
$tokenFile = Join-Path $state 'github_token'
$startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'neolab_mise_a_jour.cmd'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say($message, $color = 'Gray') {
    Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $message) -Encoding UTF8
    if (-not $Quiet) { Write-Host $message -ForegroundColor $color }
}
function Fail($message) { Say "ÉCHEC : $message" Red; exit 1 }

if ($NoAuto) {
    Remove-Item $startup -ErrorAction SilentlyContinue
    Say "Mise à jour automatique retirée." Green
    exit 0
}
if ($Auto) {
    $self = $MyInvocation.MyCommand.Path
    $line = "@start `"`" /min powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$self`" -Quiet"
    Set-Content -Path $startup -Value $line -Encoding ASCII
    Say "Mise à jour automatique à chaque ouverture de session : $startup (journal : $log)" Green
}

# --- Docker and the container
$docker = (Get-Command docker.exe -ErrorAction SilentlyContinue).Source
if (-not $docker) {
    $docker = @("$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
                "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $docker) { Fail "docker.exe introuvable : installer le warehouse d'abord." }
$waited = 0
& $docker info *> $null
while ($LASTEXITCODE -ne 0 -and $waited -lt 600) {   # at logon, Docker Desktop takes a while
    if ($waited -eq 0) {
        $app = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $docker))) 'Docker Desktop.exe'
        if ((Test-Path $app) -and -not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) { Start-Process $app }
        Say "attente de Docker…"
    }
    Start-Sleep -Seconds 10; $waited += 10
    & $docker info *> $null
}
if ($LASTEXITCODE -ne 0) { Fail "Docker ne répond pas : lancer Docker Desktop, puis relancer." }
& $docker container inspect $container *> $null
if ($LASTEXITCODE -ne 0) { Fail "conteneur $container absent : installer le warehouse d'abord." }
& $docker start $container *> $null
$waited = 0
do {
    & $docker exec $container sh -c 'test -f $NEOLAB_STATE/ready && pg_isready -q -h 127.0.0.1' *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 5; $waited += 5
} while ($waited -lt 180)
if ($LASTEXITCODE -ne 0) { Fail "la base du conteneur ne répond pas." }

# --- Latest version on GitHub (anonymous first; private repository: saved token)
function Read-Token {
    if (-not (Test-Path $tokenFile)) { return $null }
    try {
        $secure = Get-Content $tokenFile | ConvertTo-SecureString
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    } catch { return $null }
}
function Get-GitHub($url, $token, $outFile, $accept) {
    $headers = @{ 'User-Agent' = 'neolab-update'; 'Accept' = $accept }
    if ($token) { $headers['Authorization'] = "Bearer $token" }
    if ($outFile) { Invoke-WebRequest -UseBasicParsing -Uri $url -Headers $headers -OutFile $outFile -ErrorAction Stop; return $null }
    return (Invoke-WebRequest -UseBasicParsing -Uri $url -Headers $headers -ErrorAction Stop).Content
}
$api = "https://api.github.com/repos/$Repo"
$token = Read-Token
$latest = $null
for ($try = 0; $try -lt 2 -and -not $latest; $try++) {
    try {
        $latest = ([string](Get-GitHub "$api/commits/$Branch" $token $null 'application/vnd.github.sha')).Trim()
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        if ($code -notin 401, 403, 404) { Fail "GitHub injoignable ($($_.Exception.Message))." }
        if ($Quiet) { Fail "accès GitHub refusé : lancer mettre_a_jour_windows.bat à la main pour donner un jeton." }
        if ($try -gt 0) { Fail "jeton refusé par GitHub (dépôt $Repo) : vérifier ses droits, puis relancer." }
        Write-Host "`nDépôt privé : jeton GitHub en lecture seule nécessaire (une seule fois)." -ForegroundColor Yellow
        Write-Host "  github.com > Settings > Developer settings > Fine-grained tokens > Generate new token"
        Write-Host "  Repository access : Only select repositories > $Repo ; Permissions > Contents : Read-only"
        $secure = Read-Host "Coller le jeton (il ne s'affiche pas)" -AsSecureString
        $secure | ConvertFrom-SecureString | Set-Content $tokenFile
        $token = Read-Token
    }
}
$current = ((& $docker exec $container sh -c 'cat /opt/neolab/version 2>/dev/null') | Out-String).Trim()
if ($current -eq $latest) {
    Say "Déjà à jour ($($latest.Substring(0, 7)))." Green
    if (-not $Quiet -and -not $Auto) { Write-Host "Pour une mise à jour automatique à chaque session : mettre_a_jour_windows.bat -Auto" }
    exit 0
}
Say "Mise à jour : $(if ($current) { $current.Substring(0, 7) } else { 'version d''installation' }) -> $($latest.Substring(0, 7))"

# --- Download, copy into the container, apply
$work = Join-Path $env:TEMP ("neolab-maj-" + $latest.Substring(0, 12))
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work | Out-Null
$archive = Join-Path $work 'code.tar.gz'
try { Get-GitHub "$api/tarball/$latest" $token $archive 'application/vnd.github+json' }
catch { Fail "téléchargement du code impossible ($($_.Exception.Message))." }
& tar.exe -xzf $archive -C $work
$source = Get-ChildItem $work -Directory | Select-Object -First 1
if ($LASTEXITCODE -ne 0 -or -not $source -or -not (Test-Path (Join-Path $source.FullName 'docker\allinone\neolab-update'))) {
    Fail "archive du code incomplète."
}
& $docker cp "$($source.FullName)\." "${container}:/opt/neolab/IDEA/" *> $null
if ($LASTEXITCODE -ne 0) { Fail "copie du code dans le conteneur impossible." }
Say "Application dans le conteneur (1 à 3 minutes)…"
$output = & $docker exec $container bash /opt/neolab/IDEA/docker/allinone/neolab-update $latest 2>&1
$output | ForEach-Object { Add-Content -Path $log -Value "  $_" -Encoding UTF8 }
if ($LASTEXITCODE -ne 0) {
    if (-not $Quiet) { $output | Select-Object -Last 25 | ForEach-Object { Write-Host "  $_" } }
    Fail "mise à jour refusée par le conteneur (détail dans $log)."
}
$travail = Join-Path $HOME 'neolab-travail'
New-Item -ItemType Directory -Force $travail | Out-Null
& $docker cp "${container}:/opt/neolab/workspace/." "$travail\" *> $null
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
Say "À JOUR ($($latest.Substring(0, 7))). Rouvrir une nouvelle conversation dans l'assistant." Green
