param([ValidateSet('start','stop','status')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root 'data/tooling/python/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Python portable absent dans data/tooling/python.' }
& $python (Join-Path $PSScriptRoot 'local_warehouse.py') $Action
exit $LASTEXITCODE
