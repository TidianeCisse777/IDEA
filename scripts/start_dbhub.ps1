param([switch]$Check)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $Check -and -not $env:WAREHOUSE_READER_PASSWORD) {
    $credentialsPath = Join-Path $root 'data/local_warehouse/credentials.json'
    if (Test-Path -LiteralPath $credentialsPath) {
        $credentials = Get-Content -Raw -LiteralPath $credentialsPath | ConvertFrom-Json
        $env:WAREHOUSE_READER_PASSWORD = $credentials.reader
    }
}
if (-not $env:WAREHOUSE_READER_PASSWORD) {
    throw 'WAREHOUSE_READER_PASSWORD requis; aucun fallback propriétaire.'
}
if (-not $env:WAREHOUSE_READER_HOST) { $env:WAREHOUSE_READER_HOST = '127.0.0.1' }
if ($Check) {
    Write-Output 'Configuration DbHub prête (credentials non affichés).'
    return
}
$node = Get-ChildItem (Join-Path $root 'data/tooling/node-*/node.exe') -ErrorAction SilentlyContinue | Select-Object -First 1
if ($node) { $env:PATH = $node.DirectoryName + ';' + $env:PATH }
$entry = Join-Path $root 'data/tooling/dbhub/node_modules/@bytebase/dbhub/dist/index.js'
if (-not (Test-Path -LiteralPath $entry)) { throw 'DbHub local non installé dans data/tooling/dbhub.' }
& node $entry --transport stdio --config (Join-Path $root 'dbhub/warehouse.toml')
exit $LASTEXITCODE
