[CmdletBinding()]
param(
    [string]$Destination = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'TRACE'),
    [string]$ShortcutDirectory = [Environment]::GetFolderPath('Desktop'),
    [ValidateRange(1024,65535)][int]$Port = 8000,
    [switch]$SkipStart
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$source = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$source = [IO.Path]::GetFullPath($source).TrimEnd('\')
$Destination = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
if ($Destination -eq $source -or $Destination.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Extract the package outside the destination folder, then run Install again.'
}
if (Test-Path $Destination) {
    throw "Destination already exists: $Destination. Use its Start TRACE.cmd to launch. Nothing was overwritten."
}
function New-TraceSecret {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
}
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
$excluded = @('.git','.env','.venv','__pycache__','.pytest_cache','logs','dist')
Get-ChildItem -LiteralPath $source -Force | Where-Object { $_.Name -notin $excluded } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
}
$password = New-TraceSecret
$graphPassword = New-TraceSecret
$environment = @"
POSTGRES_PASSWORD=$password
DATABASE_URL=postgresql://trace:$password@postgres:5432/trace
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=$graphPassword
REDIS_URL=redis://redis:6379/0
OPENSEARCH_URL=http://opensearch:9200
EVIDENCE_BACKEND=filesystem
EVIDENCE_DIRECTORY=/var/lib/trace/evidence
TED_BASE_URL=https://api.ted.europa.eu
GLEIF_BASE_URL=https://api.gleif.org/api/v1
CELLAR_BASE_URL=https://publications.europa.eu/resource/celex
HTTP_TIMEOUT_SECONDS=30
TRACE_ENV=desktop
TRACE_PORT=$Port
"@
[IO.File]::WriteAllText((Join-Path $Destination '.env'), $environment, (New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText((Join-Path $Destination '.trace-desktop'), '0.3.0-desktop.1')
New-Item -ItemType Directory -Path $ShortcutDirectory -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$linkPath = Join-Path $ShortcutDirectory 'TRACE.lnk'
if (Test-Path $linkPath) { $linkPath = Join-Path $ShortcutDirectory ('TRACE-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.lnk') }
$link = $shell.CreateShortcut($linkPath)
$link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$link.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Destination 'desktop\windows\Start.ps1') + '"'
$link.WorkingDirectory = $Destination
$link.Description = 'Start TRACE and open the investigation console'
$link.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',14'
$link.Save()
Write-Host "TRACE installed: $Destination"
Write-Host "Shortcut: $linkPath"
if (-not $SkipStart) { & (Join-Path $Destination 'desktop\windows\Start.ps1') }
