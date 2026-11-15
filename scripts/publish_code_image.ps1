# Publie le petit paquet « code seul » (quelques Mo) à côté de l'image avec données, dans le même paquet privé
# GitHub (ghcr.io/<compte>/neolab-warehouse, étiquettes :code et :code-<version>). Les collègues l'appliquent avec
# update_warehouse_windows.bat ou bash update_warehouse.sh (connexion read:packages de l'installation, aucun
# accès au dépôt), et l'installeur l'applique juste après l'installation.
#
#     powershell -ExecutionPolicy Bypass -File publish_code_image.ps1 [-Owner TidianeCisse777]
#
# Publie le dernier commit de la branche mcp-neolab tel qu'il est sur GitHub (pas un travail local non poussé),
# extrait par git archive : seuls les fichiers suivis par git, jamais les données ignorées (data/...). Le paquet
# contient /IDEA et la liste des versions antérieures de la branche (.neolab_commits), qui empêche tout retour
# en arrière chez les collègues. Prérequis : « docker login ghcr.io » avec write:packages (déjà fait pour l'image).
param([string]$Owner = 'TidianeCisse777', [string]$Branch = 'mcp-neolab')
$ErrorActionPreference = 'Continue'
function Fail($text) { Write-Host "`nÉCHEC : $text" -ForegroundColor Red; exit 1 }
$root = Split-Path -Parent $PSScriptRoot
$repo = "ghcr.io/$($Owner.ToLower())/neolab-warehouse"

& git -C $root fetch -q origin $Branch
if ($LASTEXITCODE -ne 0) { Fail "GitHub injoignable (git fetch)." }
$sha = ((& git -C $root rev-parse "origin/$Branch") | Out-String).Trim()
if ($sha -notmatch '^[0-9a-f]{40}$') { Fail "version de origin/$Branch illisible." }
$short = $sha.Substring(0, 7)

$work = Join-Path $env:TEMP "neolab-code-$short"
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work | Out-Null
# core.autocrlf=false: on Windows, git archive otherwise writes CRLF and the container's shell scripts break
# ("set: pipefail: invalid option name", seen on 14 November 2026).
& git -C $root -c core.autocrlf=false archive --format=tar --prefix=IDEA/ -o (Join-Path $work 'code.tar') $sha
if ($LASTEXITCODE -ne 0) { Fail "extraction du code impossible (git archive)." }
# Windows' own tar: from Git Bash, Git's tar reads "C:\..." as a remote host.
$tar = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path $tar)) { $tar = 'tar.exe' }
& $tar -xf (Join-Path $work 'code.tar') -C $work
if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $work 'IDEA\docker\allinone\neolab-update'))) { Fail "code extrait incomplet." }
Remove-Item (Join-Path $work 'code.tar')
$probe = [IO.File]::ReadAllBytes((Join-Path $work 'IDEA\docker\allinone\neolab-update'))
if ($probe -contains 13) { Fail "fins de ligne Windows dans le code extrait : rien n'est publié." }
# Every version of the branch up to this one, LF line endings (read by bash on Mac and by PowerShell).
$commits = (& git -C $root rev-list $sha) -join "`n"
[IO.File]::WriteAllText((Join-Path $work 'IDEA\.neolab_commits'), "$commits`n", (New-Object Text.UTF8Encoding $false))
$dockerfile = "FROM scratch`nCOPY IDEA /IDEA`nLABEL neolab.commit=$sha`nCMD [`"none`"]`n"
[IO.File]::WriteAllText((Join-Path $work 'Dockerfile'), $dockerfile, (New-Object Text.UTF8Encoding $false))

Write-Host "== Paquet code $short"
& docker build -q -t "${repo}:code-$short" $work | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "fabrication du paquet impossible (docker build)." }
& docker tag "${repo}:code-$short" "${repo}:code"
& docker push -q "${repo}:code-$short" | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "publication refusée : vérifier « docker login ghcr.io » (write:packages)." }
& docker push -q "${repo}:code" | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "publication de l'étiquette :code refusée." }
& docker rmi "${repo}:code-$short" "${repo}:code" *> $null
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
Write-Host "`nPUBLIÉ : ${repo}:code ($short). Les collègues : update_warehouse_windows.bat ou bash update_warehouse.sh." -ForegroundColor Green
