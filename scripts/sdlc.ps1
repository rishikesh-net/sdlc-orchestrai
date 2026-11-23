[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$python = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    try {
        & python -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = "python" }
    } catch {}
}

if (-not $python -and (Get-Command python3 -ErrorAction SilentlyContinue)) {
    try {
        & python3 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = "python3" }
    } catch {}
}

if (-not $python -and (Test-Path "$env:LOCALAPPDATA\Python\bin\python.exe")) {
    $python = "$env:LOCALAPPDATA\Python\bin\python.exe"
}

if (-not $python) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) {
            $python = $cand
            break
        }
    }
}

if (-not $python) {
    Write-Error "Python 3 is required to run sdlc. Please install Python 3."
    exit 1
}

$scriptPath = Join-Path $PSScriptRoot "sdlc.py"
& $python $scriptPath @ScriptArgs
exit $LASTEXITCODE
