[CmdletBinding()]
param([switch]$NoBrowser)
. "$PSScriptRoot\Common.ps1"
$logDirectory = Join-Path $TraceRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Start-Transcript -Path (Join-Path $logDirectory ('start-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')) | Out-Null
try {
    if (-not (Test-Path (Join-Path $TraceRoot '.env'))) { throw 'Run Install TRACE.cmd first.' }
    Assert-TraceDocker
    $port = Get-TracePort
    Write-Host 'Starting TRACE services. First launch downloads and builds the containers.'
    Invoke-TraceCompose -ComposeArgs @('up','-d','--build')
    $url = "http://127.0.0.1:$port"
    $deadline = (Get-Date).AddMinutes(5)
    $ready = $false
    do {
        try {
            $health = Invoke-RestMethod "$url/ready" -TimeoutSec 10
            if ($health.status -eq 'ready') { $ready = $true; break }
        } catch { Start-Sleep -Seconds 3 }
    } while ((Get-Date) -lt $deadline)
    if (-not $ready) { Invoke-TraceCompose -ComposeArgs @('logs','--tail','60','api','migrate'); throw 'TRACE is not ready. See logs or run Diagnose TRACE.cmd.' }
    Write-Host "TRACE is ready: $url/ui/"
    if (-not $NoBrowser) { Open-TraceWindow "$url/ui/" }
    $bootstrap = Join-Path $logDirectory 'bootstrap.json'
    if (-not (Test-Path $bootstrap)) {
        Write-Host 'Loading initial public records: GLEIF, TED and EUR-Lex.'
        $report = Invoke-TraceCompose -ComposeArgs @('exec','-T','api','python','/app/scripts/bootstrap_sources.py')
        $report | Set-Content -Encoding UTF8 $bootstrap
        Write-Host "Initial source results saved to $bootstrap. Failed sources can be retried from the console."
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host 'Press Enter to close' | Out-Null
    exit 1
} finally { Stop-Transcript | Out-Null }
