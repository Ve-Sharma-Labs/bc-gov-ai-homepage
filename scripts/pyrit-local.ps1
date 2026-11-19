param(
    [ValidateSet('Ready', 'Check', 'Stop')]
    [string]$Mode = 'Ready',
    [ValidateRange(1024, 65535)]
    [int]$Port = 18765,
    [switch]$Restart,
    [switch]$RenewWindow,
    [switch]$BrowseOnly,
    [switch]$NoBrowser,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root '.cache\copyrit'
$python = Join-Path $runtime '.venv\Scripts\python.exe'
$config = Join-Path $runtime 'copyrit.yaml'
$url = "http://127.0.0.1:$Port"

function Get-OwnedListener {
    $connections = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    foreach ($connection in $connections) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)"
        if ($connection.LocalAddress -ne '127.0.0.1' -or -not $process.CommandLine -or
            -not $process.CommandLine.Contains('pyrit.backend.pyrit_backend') -or
            -not $process.CommandLine.Contains($config)) {
            throw "Port $Port belongs to a different process. Nothing was stopped."
        }
    }
    return @($connections.OwningProcess | Select-Object -Unique)
}

$owned = @(Get-OwnedListener)
if ($Mode -eq 'Stop') {
    if ($owned.Count -gt 0 -and -not $Restart) {
        $answer = Read-Host 'Stop the owned PyRIT server? Active tests will stop. [y/N]'
        if ($answer -notmatch '^(y|yes)$') { return }
    }
    foreach ($serverId in $owned) { Stop-Process -Id $serverId }
    Write-Output 'Owned PyRIT server stopped; data and budgets were preserved.'
    return
}

if ($Mode -eq 'Check') {
    if (-not (Test-Path -LiteralPath $python)) { throw 'PyRIT is not installed. Run npm run pyrit:ready.' }
    $arguments = @('-m', 'bc_pyrit.local', 'check', '--root', $root, '--port', "$Port")
    if ($Json) { $arguments += '--json' }
    & $python @arguments
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $python)) {
    $version = & python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
    if ($LASTEXITCODE -ne 0 -or $version -ne '3.14') { throw 'Install Python 3.14 first.' }
    & python -m venv (Join-Path $runtime '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated PyRIT environment.' }
    $wheel = Join-Path $runtime 'wheels\pyrit-1.2.0-py3-none-any.whl'
    if (Test-Path -LiteralPath $wheel) {
        $hash = (Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne 'b573286ab366273a8fec8bc32024b029e24e3b1a170696a2ee66c56d01de3547') {
            throw 'The local PyRIT wheel does not match the reviewed release.'
        }
        & $python -m pip install $wheel
        if ($LASTEXITCODE -ne 0) { throw 'PyRIT installation failed; TLS verification remains enabled.' }
    }
    & $python -m pip install --editable (Join-Path $root 'evaluations\pyrit')
    if ($LASTEXITCODE -ne 0) { throw 'PyRIT dependencies could not be installed.' }
}

& $python -c 'from importlib.metadata import version; import bc_pyrit.local; assert version("pyrit") == "1.2.0"'
if ($LASTEXITCODE -ne 0) {
    throw 'The isolated environment is incomplete. Install evaluations\pyrit into it before retrying.'
}
$source = Join-Path $runtime 'source'
if (Test-Path -LiteralPath $source) {
    $revision = & git -C $source rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $revision -ne '5398ad19e364659f9b7d686fb1eb398045a63273') {
        throw 'The optional PyRIT source checkout is not the reviewed release.'
    }
    $dirty = & git -C $source --no-pager status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0 -or $dirty) {
        throw 'The optional PyRIT source checkout has tracked changes; review them before starting.'
    }
}

if ($owned.Count -gt 0 -and -not $Restart -and -not $RenewWindow -and -not $BrowseOnly) {
    $status = & $python -m bc_pyrit.local check --root $root --port $Port --json 2>$null
    if ($LASTEXITCODE -eq 0 -and ($status | ConvertFrom-Json).window.ready) {
        & $python -m bc_pyrit.local check --root $root --port $Port
        if (-not $NoBrowser) { Start-Process $url }
        return
    }
}
if ($owned.Count -gt 0 -and -not $Restart) {
    $answer = Read-Host 'Reload the owned PyRIT server to load this pack? Active tests will stop. [y/N]'
    if ($answer -notmatch '^(y|yes)$') { throw 'Reload cancelled; no data or limits were changed.' }
}

# Verify/download data before interrupting the existing server.
& $python -m bc_pyrit.local sources --root $root | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'The pinned data pack is unavailable; the current server was left alone.' }
$window = & $python -m bc_pyrit.local window --root $root
if ($LASTEXITCODE -ne 0) { throw 'The manual-window configuration could not be read.' }
$window = $window | ConvertFrom-Json
if ($window.renewable -and -not $RenewWindow -and -not $BrowseOnly) {
    $answer = Read-Host 'Open a new one-hour, 20-request window? Daily model limits stay unchanged. [y/N]'
    if ($answer -match '^(y|yes)$') { $RenewWindow = $true } else { $BrowseOnly = $true }
}

foreach ($serverId in $owned) { Stop-Process -Id $serverId }
$lockPath = Join-Path $runtime 'launcher.lock'
$deadline = [DateTime]::UtcNow.AddSeconds(15)
do {
    try {
        $lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
        break
    }
    catch [System.IO.IOException] {
        if ([DateTime]::UtcNow -ge $deadline) {
            throw 'Another PyRIT setup process still owns the startup lock. Nothing was reset.'
        }
        Start-Sleep -Milliseconds 250
    }
} while ($true)
try {
    $arguments = @('-m', 'bc_pyrit.local', 'prepare', '--root', $root, '--port', "$Port")
    if ($RenewWindow) { $arguments += '--renew-window' }
    if ($BrowseOnly) { $arguments += '--browse-only' }
    & $python @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Local preparation failed; no attacks were launched.' }
    $arguments = @('-m', 'bc_pyrit.local', 'serve', '--root', $root, '--port', "$Port")
    if ($NoBrowser) { $arguments += '--no-browser' }
    Write-Output "Opening CoPyRIT at $url. Keep this terminal open; Ctrl+C stops the server."
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'PyRIT stopped with an error; inspect the startup message.' }
}
finally {
    $lock.Dispose()
}
