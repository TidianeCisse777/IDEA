# Branche les assistants sur le warehouse NeoLab déjà installé (conteneur neolab-warehouse), sans rien
# réinstaller. Relançable autant de fois que voulu. Double-cliquer brancher_assistants_windows.bat, ou :
#
#     powershell -ExecutionPolicy Bypass -File brancher_assistants_windows.ps1
#     powershell -ExecutionPolicy Bypass -File brancher_assistants_windows.ps1 -CodexWsl
#
# Écrit le chemin complet de docker.exe (les applications lancées depuis le menu Démarrer n'ont pas
# forcément le PATH du terminal : « program not found ») dans :
#   Claude Code (ligne de commande et extension VS Code), Codex (config.toml : ligne de commande, extension
#   VS Code, application), VS Code / Copilot (mcp.json), Claude Desktop (claude_desktop_config.json).
# -CodexWsl : pour une application Codex réglée pour exécuter l'agent dans WSL (chemin /mnt/c/...).
# Chaque fichier modifié est d'abord copié en <fichier>.avant-neolab. Aucun mot de passe écrit ni affiché.
param([switch]$CodexWsl)
$ErrorActionPreference = 'Continue'
$container = 'neolab-warehouse'
$name = 'neolab-warehouse'
$mcpArgs = @('exec', '-i', $container, 'neolab-mcp')

function Ok($message) { Write-Host "  OK  $message" -ForegroundColor Green }
function Note($message) { Write-Host "  --  $message" -ForegroundColor Yellow }
function Fail($message) { Write-Host "`nÉCHEC : $message" -ForegroundColor Red; exit 1 }
function Write-Utf8($path, $text) {
    # UTF-8 without BOM: the TOML and JSON readers of the applications may refuse a BOM.
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}
function Backup($path) {
    if ((Test-Path $path) -and -not (Test-Path "$path.avant-neolab")) { Copy-Item $path "$path.avant-neolab" }
}

function Set-CodexServer($path, $command, $arguments) {
    # Replaces the [mcp_servers.neolab-warehouse] table (and its sub-tables), keeps everything else.
    $kept = New-Object System.Collections.Generic.List[string]
    $skip = $false
    if (Test-Path $path) {
        foreach ($line in [System.IO.File]::ReadAllLines($path)) {
            $t = $line.Trim()
            if ($t -match '^\[') {
                $skip = ($t -match '^\[\s*mcp_servers\.("?)neolab-warehouse\1\s*[\].]')
            }
            if (-not $skip) { $kept.Add($line) }
        }
    }
    while ($kept.Count -gt 0 -and $kept[$kept.Count - 1].Trim() -eq '') { $kept.RemoveAt($kept.Count - 1) }
    $quoted = ($arguments | ForEach-Object { '"' + $_ + '"' }) -join ', '
    $block = @('', "[mcp_servers.$name]", "command = '$command'", "args = [$quoted]", 'startup_timeout_sec = 60')
    if ($kept.Count -eq 0) { $block = $block[1..($block.Count - 1)] }
    Write-Utf8 $path (((@($kept) + $block) -join "`n") + "`n")
}

function Set-JsonServer($path, $key, $entry) {
    # Adds the server under $key in a JSON file; leaves a file it cannot read (comments, errors) untouched.
    $data = New-Object PSObject
    if ((Test-Path $path) -and ((Get-Content -Raw $path) -match '\S')) {
        try { $data = Get-Content -Raw -Encoding UTF8 $path | ConvertFrom-Json -ErrorAction Stop }
        catch { return $false }
    }
    if (-not ($data.PSObject.Properties.Name -contains $key)) {
        $data | Add-Member -NotePropertyName $key -NotePropertyValue (New-Object PSObject)
    }
    $servers = $data.$key
    if ($servers.PSObject.Properties.Name -contains $name) { $servers.PSObject.Properties.Remove($name) }
    $servers | Add-Member -NotePropertyName $name -NotePropertyValue ([PSCustomObject]$entry)
    Write-Utf8 $path ($data | ConvertTo-Json -Depth 30)
    return $true
}

if ($env:NEOLAB_FUNCTIONS_ONLY) { return }   # tests: load the functions above only

Write-Host "`n== 1/4 Docker"
$docker = (Get-Command docker.exe -ErrorAction SilentlyContinue).Source
if (-not $docker) {
    $docker = @("$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
                "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $docker) { Fail "docker.exe introuvable : installer le warehouse d'abord (installer_windows.bat)." }
Ok "docker : $docker"
& $docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $app = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $docker))) 'Docker Desktop.exe'
    if (Test-Path $app) { Write-Host "  démarrage de Docker Desktop…"; Start-Process $app }
    $waited = 0
    do {
        Start-Sleep -Seconds 5; $waited += 5
        & $docker info *> $null
    } while ($LASTEXITCODE -ne 0 -and $waited -lt 300)
    if ($LASTEXITCODE -ne 0) { Fail "Docker ne répond pas : ouvrir Docker Desktop, attendre « Engine running », relancer." }
}
Ok "Docker répond"

Write-Host "`n== 2/4 Base de données"
& $docker container inspect $container *> $null
if ($LASTEXITCODE -ne 0) { Fail "conteneur $container absent : lancer d'abord installer_windows.bat." }
& $docker start $container *> $null
$waited = 0
do {
    $check = (& $docker exec $container neolab-check 2>&1) -join "`n"
    if ($check -match 'PASS') { break }
    Start-Sleep -Seconds 5; $waited += 5
} while ($waited -lt 180)
if ($check -notmatch 'PASS') { Write-Host $check; Fail "le serveur MCP ne répond pas (message ci-dessus)." }
Ok "base prête, serveur MCP : PASS"
$work = Join-Path $HOME 'neolab-travail'
New-Item -ItemType Directory -Force $work | Out-Null
& $docker cp "${container}:/opt/neolab/workspace/." "$work\" *> $null
Ok "dossier de travail : $work"

Write-Host "`n== 3/4 Assistants"
$claudeLocal = Join-Path $HOME '.local\bin'
if (Test-Path $claudeLocal) { $env:Path = "$claudeLocal;$env:Path" }
if (Get-Command claude -ErrorAction SilentlyContinue) {
    & claude mcp remove $name -s user *> $null
    & claude mcp add --scope user $name '--' $docker @mcpArgs *> $null
    if ($LASTEXITCODE -eq 0) { Ok "Claude Code (terminal, extension VS Code)" } else { Note "Claude Code : enregistrement refusé" }
} else { Note "Claude Code non installé : sauté" }

$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
New-Item -ItemType Directory -Force $codexHome | Out-Null
$codexToml = Join-Path $codexHome 'config.toml'
$codexCommand = $docker
if ($CodexWsl) {
    $codexCommand = '/mnt/' + $docker.Substring(0, 1).ToLower() + ($docker.Substring(2) -replace '\\', '/')
}
Backup $codexToml
Set-CodexServer $codexToml $codexCommand $mcpArgs
Ok "Codex (terminal, extension VS Code, application) : $codexToml"

$vscode = Join-Path $env:APPDATA 'Code\User'
if (Test-Path $vscode) {
    $file = Join-Path $vscode 'mcp.json'
    Backup $file
    if (Set-JsonServer $file 'servers' @{ type = 'stdio'; command = $docker; args = $mcpArgs }) { Ok "VS Code (Copilot) : $file" }
    else { Note "VS Code : $file illisible (commentaires ?), non modifié : y ajouter le serveur à la main (LISEZMOI)" }
} else { Note "VS Code non installé : sauté" }

$claudeDirs = @(Join-Path $env:APPDATA 'Claude') + @(Get-ChildItem "$env:LOCALAPPDATA\Packages\Claude_*\LocalCache\Roaming\Claude" -Directory -ErrorAction SilentlyContinue | ForEach-Object FullName)
$found = $false
foreach ($dir in $claudeDirs) {
    if (-not (Test-Path $dir)) { continue }
    $found = $true
    $file = Join-Path $dir 'claude_desktop_config.json'
    Backup $file
    if (Set-JsonServer $file 'mcpServers' @{ command = $docker; args = $mcpArgs }) { Ok "Claude Desktop : $file" }
    else { Note "Claude Desktop : $file illisible, non modifié" }
}
if (-not $found) { Note "Claude Desktop non installé : sauté" }

Write-Host "`n== 4/4 Fini" -ForegroundColor Green
Write-Host @"
Quitter complètement les applications (aussi l'icône près de l'horloge), puis les rouvrir :
elles ne relisent leur configuration qu'au démarrage. Ouvrir le dossier $work, puis demander :
« Combien d'objets validés dans am_leg3 ? »

Si l'application Codex dit encore « program not found », elle exécute probablement l'agent dans WSL :
relancer avec  brancher_assistants_windows.bat -CodexWsl
"@
