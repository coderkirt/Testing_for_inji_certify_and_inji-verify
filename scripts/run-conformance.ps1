# Windows entry point for the same one-command harness.
param(
    [ValidateSet("certify", "verify")]
    [string]$Component,
    [switch]$Combined,
    [switch]$SkipCompose,
    [switch]$SkipTestrig,
    [switch]$Parallel,
    [string]$OfficialScript,
    [string]$DiffAgainst
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root "compose\docker-compose.yml"
$EnvFile = Join-Path $Root "compose\.env"
$Example = Join-Path $Root "compose\.env.example"

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

if (-not $SkipCompose) {
    $services = @("mongodb", "server", "nginx")
    if ($Mode -in @("combined", "certify")) {
        $services += @("certify-db", "certify", "certify-nginx")
    }
    if ($Mode -in @("combined", "verify")) {
        $services += @("verify-db", "verify-service", "verify-ui")
    }
    Write-Host "Starting services: $($services -join ' ')"
    Invoke-Compose -ComposeArgs (@("up", "-d") + $services)
}

if (-not $env:CONFORMANCE_SERVER) { $env:CONFORMANCE_SERVER = "https://localhost.emobix.co.uk:8443/" }
if ($env:ENV_ENDPOINT -and -not $env:CERTIFY_ISSUER_URL) { $env:CERTIFY_ISSUER_URL = $env:ENV_ENDPOINT }
if (-not $env:CERTIFY_ISSUER_URL) { $env:CERTIFY_ISSUER_URL = "http://certify-nginx" }
if (-not $env:VERIFY_ENDPOINT) { $env:VERIFY_ENDPOINT = "http://verify-service:8080/v1/verify" }

$OutDir = Join-Path $Root "results\$Mode"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$Runner = @(
    $Python, (Join-Path $Root "runner\run_conformance.py"),
    "--output-dir", $OutDir,
    "--suite-url", $env:CONFORMANCE_SERVER
)
if ($Combined) { $Runner += "--combined" } else { $Runner += @("--component", $Component) }
if ($Parallel) { $Runner += "--parallel" }
if ($OfficialScript) { $Runner += @("--official-script", $OfficialScript) }
if ($DiffAgainst) { $Runner += @("--diff-against", $DiffAgainst) }

Write-Host "Running $Mode conformance"
& $Runner[0] $Runner[1..($Runner.Length - 1)]
$RunnerExit = $LASTEXITCODE
if ($RunnerExit -ne 0) {
    Write-Host "Conformance runner failed with exit code $RunnerExit"
    exit $RunnerExit
}

if (-not $SkipTestrig) {
    $SuiteXml = "src/test/resources/testng-$Mode.xml"
    mvn -f (Join-Path $Root "testrig-bridge\pom.xml") -Pconformance-suite test `
        "-DsuiteXmlFile=$SuiteXml" `
        "-Dconformance.results=$OutDir\results.json" `
        "-Dconformance.component=$Mode" `
        "-Dconformance.reuseResults=true" `
        "-Dconformance.repoRoot=$Root"
}

exit $RunnerExit
