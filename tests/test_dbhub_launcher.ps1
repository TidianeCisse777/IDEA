$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $root 'scripts/start_dbhub.ps1'
$previous = $env:WAREHOUSE_READER_PASSWORD
try {
    $env:WAREHOUSE_READER_PASSWORD = $null
    $failed = $false
    try { & $launcher -Check } catch { $failed = $true }
    if (-not $failed) { throw 'Le lanceur doit refuser un credential absent' }
    $env:WAREHOUSE_READER_PASSWORD = 'fixture-not-a-real-password'
    $result = & $launcher -Check
    if ($result -ne 'Configuration DbHub prête (credentials non affichés).') {
        throw 'Le contrôle doit réussir sans exposer le credential'
    }
    $config = Get-Content -Raw (Join-Path $root 'dbhub/warehouse.toml')
    foreach ($fragment in @('readonly = true', 'max_rows = 1000', 'user = "warehouse_reader"', 'search_path = "explore"', '${WAREHOUSE_READER_PASSWORD}')) {
        if (-not $config.Contains($fragment)) { throw "Contrat manquant : $fragment" }
    }
    Write-Output 'PASS : credentials obligatoires, contrôle sans secret et accès lecteur.'
} finally {
    $env:WAREHOUSE_READER_PASSWORD = $previous
}
