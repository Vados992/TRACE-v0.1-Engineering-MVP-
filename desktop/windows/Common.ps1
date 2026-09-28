Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$TraceRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
function Invoke-TraceCompose {
    param([string[]]$ComposeArgs)
    & docker compose --project-name trace-desktop --project-directory $TraceRoot --env-file (Join-Path $TraceRoot '.env') -f (Join-Path $TraceRoot 'compose.desktop.yml') @ComposeArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed (exit $LASTEXITCODE)." }
}
function Get-TracePort {
    $line = Get-Content (Join-Path $TraceRoot '.env') | Where-Object { $_ -match '^TRACE_PORT=\d+$' } | Select-Object -First 1
    if ($line) { return [int]($line -split '=',2)[1] }
    return 8000
}
function Assert-TraceDocker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install Docker Desktop with Linux containers first: https://docs.docker.com/desktop/setup/install/windows-install/'
    }
    $info = & docker info --format '{{json .}}' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop, wait for the engine, then run TRACE again.' }
    $engine = $info | ConvertFrom-Json
    if ($engine.OSType -ne 'linux') { throw 'Switch Docker Desktop to Linux containers.' }
    if ($engine.MemTotal -lt 5GB) { Write-Warning 'The full stack may need at least 6 GB allocated to Docker. 8 GB is recommended.' }
    & docker compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }
}
function Open-TraceWindow([string]$Url) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
    )
    $edge = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($edge) { Start-Process -FilePath $edge -ArgumentList @("--app=$Url") }
    else { Start-Process $Url }
}
