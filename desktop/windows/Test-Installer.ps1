$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$testHome = Join-Path $env:TEMP ('TRACE test ' + [guid]::NewGuid().ToString('N'))
$destination = Join-Path $testHome 'Desktop with spaces\TRACE'
$shortcuts = Split-Path $destination -Parent
try {
    Get-ChildItem "$root\desktop\windows\*.ps1" | ForEach-Object {
        $tokens=$null; $errors=$null
        [Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$errors) | Out-Null
        if ($errors.Count -gt 0) { throw ($errors | Out-String) }
    }
    & "$PSScriptRoot\Install.ps1" -Destination $destination -ShortcutDirectory $shortcuts -SkipStart
    foreach ($file in @('compose.desktop.yml','.env','Start TRACE.cmd','services\api\app\main.py','services\api\static\app.js')) {
        if (-not (Test-Path (Join-Path $destination $file))) { throw "Missing $file" }
    }
    $envText = Get-Content (Join-Path $destination '.env') -Raw
    if ($envText -notmatch 'POSTGRES_PASSWORD=[a-f0-9]{48}' -or $envText -match 'trace_dev_only') { throw 'Secrets were not generated.' }
    $shell=New-Object -ComObject WScript.Shell
    $link=$shell.CreateShortcut((Join-Path $shortcuts 'TRACE.lnk'))
    $expectedDirectory = [IO.Path]::GetFullPath($destination).TrimEnd('\')
    $actualDirectory = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($link.WorkingDirectory)).TrimEnd('\')
    if ($actualDirectory -ne $expectedDirectory -or $link.Arguments -notlike '*Start.ps1*') { throw "Shortcut invalid: $actualDirectory; expected $expectedDirectory" }
    $blocked=$false
    try { & "$PSScriptRoot\Install.ps1" -Destination $destination -ShortcutDirectory $shortcuts -SkipStart }
    catch { $blocked=$true }
    if (-not $blocked) { throw 'Installer overwrote existing installation.' }
    if ((Get-Content (Join-Path $destination '.env') -Raw) -ne $envText) { throw 'Existing configuration changed.' }
    Write-Host 'PASS: PowerShell parsing, installation, random credentials, shortcut, spaces, overwrite protection.'
} finally {
    if (Test-Path $testHome) { Remove-Item -LiteralPath $testHome -Recurse -Force }
}
