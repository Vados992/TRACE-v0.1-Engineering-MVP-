. "$PSScriptRoot\Common.ps1"
Assert-TraceDocker
Invoke-TraceCompose -ComposeArgs @('stop')
Write-Host 'TRACE stopped. Database and evidence volumes are preserved.'
