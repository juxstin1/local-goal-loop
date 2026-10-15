param(
    [Parameter(Mandatory = $true)]
    [string]$ServerExe,

    [Parameter(Mandatory = $true)]
    [string]$ModelPath,

    [ValidateRange(0, 9)]
    [int]$TaskIndex = 0,

    [string]$ReceiptPath = ".runtime/live-demo.json",

    [switch]$Evaluate
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".runtime"
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

if (-not (Test-Path -LiteralPath $ServerExe -PathType Leaf)) {
    throw "llama-server executable not found: $ServerExe"
}
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "GGUF model not found: $ModelPath"
}

$stdoutLog = Join-Path $runtimeRoot "llama-server.stdout.log"
$stderrLog = Join-Path $runtimeRoot "llama-server.stderr.log"
$arguments = @(
    "--model", $ModelPath,
    "--host", "127.0.0.1",
    "--port", "8080",
    "--alias", "qwen3.5-9b-q4km",
    "--ctx-size", "32768",
    "--parallel", "1",
    "--jinja",
    "--reasoning", "off",
    "--n-gpu-layers", "999"
)

$server = Start-Process `
    -FilePath $ServerExe `
    -ArgumentList $arguments `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($server.HasExited) {
            throw "llama-server exited before becoming healthy; inspect $stderrLog"
        }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 2
            if ($health.status -eq "ok") {
                $ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $ready) {
        throw "llama-server did not become healthy within 60 seconds"
    }

    Push-Location $projectRoot
    try {
        if ($Evaluate) {
            & uv run graph-engineer evaluate --receipt-path $ReceiptPath
        }
        else {
            & uv run graph-engineer demo `
                --auto-approve `
                --task-index $TaskIndex `
                --receipt-path $ReceiptPath
        }
        if ($LASTEXITCODE -ne 0) {
            throw "goal loop exited with code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id
        $server.WaitForExit()
    }
}
