. "$PSScriptRoot\Common.ps1"
Assert-TraceDocker
Invoke-TraceCompose -ComposeArgs @('ps','-a')
$port = Get-TracePort
try { Invoke-RestMethod "http://127.0.0.1:$port/api/v1/system/status" -TimeoutSec 20 | ConvertTo-Json -Depth 8 }
catch { Write-Warning 'The API is unavailable; inspect service logs below.' }
Invoke-TraceCompose -ComposeArgs @('logs','--tail','60','api','migrate')
Read-Host 'Press Enter to close' | Out-Null
