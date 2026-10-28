param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

foreach ($settings in @(
    @{ Path = 'apps\api'; Extra = 'dev' },
    @{ Path = 'ingestion'; Extra = 'azure' }
)) {
    $relative = $settings.Path
    $component = Join-Path $root $relative
    $venv = Join-Path $component '.venv'
    $executable = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $executable)) {
        & $Python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create $relative virtual environment." }
    }
    $lock = Join-Path $component 'requirements-dev.lock'
    if (Test-Path -LiteralPath $lock) {
        & $executable -m pip install -r $lock --editable $component
    } else {
        & $executable -m pip install --editable "${component}[$($settings.Extra)]"
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not install $relative dependencies." }
}

& npm --prefix (Join-Path $root 'apps\web') ci
if ($LASTEXITCODE -ne 0) { throw 'Could not install web dependencies.' }

Push-Location $root
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Could not install browser-test dependencies.' }
} finally {
    Pop-Location
}

Write-Host 'Setup complete. Use npm run dev from the repository root.'
