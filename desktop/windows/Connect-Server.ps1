[CmdletBinding()]
param([string]$SshTarget, [ValidateRange(1024,65535)][int]$LocalPort=18000, [ValidateRange(1,65535)][int]$ServerPort=8000)
. "$PSScriptRoot\Common.ps1"
if (-not $SshTarget) { $SshTarget = Read-Host 'SSH server (user@hostname), with TRACE already deployed' }
if ($SshTarget -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9][A-Za-z0-9.-]*$') { throw 'Expected user@hostname.' }
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) { throw 'Install the Windows OpenSSH Client optional feature first.' }
Write-Host "Connect using your SSH key. Keep this window open; TRACE will be at http://127.0.0.1:$LocalPort/ui/"
Write-Host 'The server host key will be verified by OpenSSH. Do not accept an unexpected fingerprint.'
& ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L "127.0.0.1:${LocalPort}:127.0.0.1:${ServerPort}" $SshTarget
if ($LASTEXITCODE -ne 0) { throw "SSH connection failed (exit $LASTEXITCODE)." }
