param(
    [Parameter(Mandatory = $true)]
    [string]$ServerExe,

    [Parameter(Mandatory = $true)]
    [string]$ModelPath,

    [string]$FixtureReceipt = ".runtime/live-evaluation-retry-2.json",

    [string]$OutputDirectory = ".runtime/spec000-evidence"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

if (-not (Test-Path -LiteralPath $ServerExe -PathType Leaf)) {
    throw "llama-server executable not found: $ServerExe"
}
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "GGUF model not found: $ModelPath"
}

$fixturePath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $FixtureReceipt))
if (-not (Test-Path -LiteralPath $fixturePath -PathType Leaf)) {
    throw "fixture receipt not found: $fixturePath"
}

$stdoutLog = Join-Path $outputRoot "llama-server.stdout.log"
$stderrLog = Join-Path $outputRoot "llama-server.stderr.log"
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
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
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
        throw "llama-server did not become healthy within 120 seconds"
    }

    Push-Location $projectRoot
    try {
        & uv run python scripts/collect-spec000-evidence.py `
            --server-exe $ServerExe `
            --server-pid $server.Id `
            --model-path $ModelPath `
            --fixture-receipt $fixturePath `
            --output-dir $outputRoot
        if ($LASTEXITCODE -ne 0) {
            throw "SPEC-000 collector recorded one or more failing gates"
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
