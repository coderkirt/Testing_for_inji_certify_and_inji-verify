# Windows entry point for the same one-command harness.
#   .\scripts\run-conformance.ps1 -Component certify
#   .\scripts\run-conformance.ps1 -Combined
#   .\scripts\run-conformance.ps1 -Component certify -ValidatePlans
param(
    [ValidateSet("certify", "verify")]
    [string]$Component,
    [switch]$Combined,
    [switch]$SkipCompose,
    [switch]$SkipTestrig,
    [switch]$Parallel,
    [switch]$ValidatePlans,
    [switch]$SaveBaseline,
    [switch]$PublishReports,
    [string]$OfficialScript,
    [string]$DiffAgainst,
    [string]$Baseline,
    [string]$ExpectedFailures,
    [string]$ExpectedSkips,
    [string]$Benchmark,
    [string[]]$Only,
    [string[]]$Skip,
    [int]$ModuleTimeout = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root "compose\docker-compose.yml"
$EnvFile = Join-Path $Root "compose\.env"
$Example = Join-Path $Root "compose\.env.example"
$HealthTimeout = if ($env:HEALTH_TIMEOUT) { [int]$env:HEALTH_TIMEOUT } else { 600 }

if (-not $Combined -and -not $Component) {
    throw "Pass -Component certify|verify or -Combined"
}

$Mode = if ($Combined) { "combined" } else { $Component }

if (-not (Test-Path $EnvFile) -and (Test-Path $Example)) {
    Copy-Item $Example $EnvFile
}

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    if (Test-Path $EnvFile) {
        docker compose --env-file $EnvFile -f $ComposeFile @ComposeArgs
    } else {
        docker compose -f $ComposeFile @ComposeArgs
    }
}

# Read a key out of compose\.env without sourcing it.
function Get-EnvValue {
    param([string]$Key, [string]$Fallback)
    if (Test-Path $EnvFile) {
        $line = Get-Content $EnvFile | Where-Object { $_ -match "^$Key=" } | Select-Object -Last 1
        if ($line) { return ($line -split "=", 2)[1] }
    }
    return $Fallback
}

function Test-Url {
    param([string]$Url)
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -kfsS -o NUL $Url 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Wait-Url {
    param([string]$Url, [string]$Name, [int]$Attempts = 60)
    Write-Host "Waiting for $Name at $Url"
    for ($i = 1; $i -le $Attempts; $i++) {
        if (Test-Url -Url $Url) {
            Write-Host "$Name is up"
            return
        }
        Start-Sleep -Seconds 5
    }
    throw "Timed out waiting for $Name ($Url)"
}

$WaitCertify = $Mode -in @("combined", "certify")
$WaitVerify = $Mode -in @("combined", "verify")

if (-not $SkipCompose) {
    $services = @("mongodb", "server", "nginx")
    if ($WaitCertify) { $services += @("certify-db", "certify", "certify-nginx") }
    if ($WaitVerify) { $services += @("verify-db", "verify-service", "verify-ui") }
    Write-Host "Starting services: $($services -join ' ')"
    # --wait blocks until every service with a healthcheck is healthy, so a
    # crash-looping container fails here rather than as conformance noise later.
    Invoke-Compose -ComposeArgs (@("up", "-d", "--wait", "--wait-timeout", "$HealthTimeout") + $services)
}

if (-not $env:CONFORMANCE_SERVER) { $env:CONFORMANCE_SERVER = "https://localhost.emobix.co.uk:8443/" }
if ($env:ENV_ENDPOINT -and -not $env:CERTIFY_ISSUER_URL) { $env:CERTIFY_ISSUER_URL = $env:ENV_ENDPOINT }
if (-not $env:CERTIFY_ISSUER_URL) { $env:CERTIFY_ISSUER_URL = "http://certify-nginx" }
if (-not $env:VERIFY_ENDPOINT) { $env:VERIFY_ENDPOINT = "http://verify-service:8080/v1/verify" }

if (-not $SkipCompose) {
    try { Wait-Url -Url $env:CONFORMANCE_SERVER -Name "OpenID conformance suite" -Attempts 48 } catch { Write-Host $_ }
    if ($WaitCertify) {
        $certifyPort = Get-EnvValue -Key "CERTIFY_NGINX_PORT" -Fallback "8091"
        Wait-Url -Url "http://127.0.0.1:$certifyPort/.well-known/openid-credential-issuer" -Name "Inji Certify (issuer metadata)"
    }
    if ($WaitVerify) {
        $verifyPort = Get-EnvValue -Key "VERIFY_HOST_PORT" -Fallback "8080"
        Wait-Url -Url "http://127.0.0.1:$verifyPort/v1/verify/actuator/health" -Name "Inji Verify (service health)"
    }
}

$OutDir = Join-Path $Root "results\$Mode"
$BaselineDir = Join-Path $Root "results"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path $BaselineDir | Out-Null

if (-not $Baseline) {
    $defaultBaseline = Join-Path $BaselineDir "baseline.json"
    if (Test-Path $defaultBaseline) { $Baseline = $defaultBaseline }
}

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$Runner = @(
    $Python, (Join-Path $Root "runner\run_conformance.py"),
    "--output-dir", $OutDir,
    "--suite-url", $env:CONFORMANCE_SERVER
)
if ($Combined) { $Runner += "--combined" } else { $Runner += @("--component", $Component) }
if ($Parallel) { $Runner += "--parallel" }
if ($ValidatePlans) { $Runner += "--validate-plans" }
if ($OfficialScript) { $Runner += @("--official-script", $OfficialScript) }
if ($DiffAgainst) { $Runner += @("--diff-against", $DiffAgainst) }
if ($Baseline) { $Runner += @("--baseline", $Baseline) }
if ($ExpectedFailures) { $Runner += @("--expected-failures", $ExpectedFailures) }
if ($ExpectedSkips) { $Runner += @("--expected-skips", $ExpectedSkips) }
if ($Benchmark) { $Runner += @("--benchmark", $Benchmark) }
if ($ModuleTimeout -gt 0) { $Runner += @("--module-timeout", "$ModuleTimeout") }
foreach ($pattern in $Only) { $Runner += @("--only", $pattern) }
foreach ($pattern in $Skip) { $Runner += @("--skip", $pattern) }

Write-Host "Running $Mode conformance"
& $Runner[0] $Runner[1..($Runner.Length - 1)]
$RunnerExit = $LASTEXITCODE

if ($ValidatePlans) { exit $RunnerExit }

if ($RunnerExit -ne 0) {
    Write-Host "Conformance runner failed with exit code $RunnerExit"
    Write-Host "Results (if written): $OutDir\results.json"
}

$ResultsFile = Join-Path $OutDir "results.json"
if (-not $SkipTestrig -and (Test-Path $ResultsFile)) {
    $SuiteXml = "src/test/resources/testng-$Mode.xml"
    Write-Host "Mapping results into TestNG suite $SuiteXml"
    mvn -f (Join-Path $Root "testrig-bridge\pom.xml") -Pconformance-suite test `
        "-DsuiteXmlFile=$SuiteXml" `
        "-Dconformance.results=$ResultsFile" `
        "-Dconformance.component=$Mode" `
        "-Dconformance.reuseResults=true" `
        "-Dconformance.repoRoot=$Root"
}

if ($PublishReports -or $env:PUSH_REPORTS_TO_S3 -eq "true") {
    Write-Host "Publishing reports"
    $s3Args = @((Join-Path $Root "runner\s3_upload.py"), "--source", (Join-Path $Root "results"), "--run-id", $Mode)
    $extent = Join-Path $Root "testrig-bridge\target\extent"
    if (Test-Path $extent) { $s3Args += @("--source", $extent) }
    & $Python @s3Args
}

if ($SaveBaseline -and $RunnerExit -eq 0 -and (Test-Path $ResultsFile)) {
    Copy-Item $ResultsFile (Join-Path $BaselineDir "baseline.json") -Force
    Write-Host "Saved benchmark baseline to $BaselineDir\baseline.json"
}

exit $RunnerExit
