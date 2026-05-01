param(
    [string]$TaskName = "AutoTiangong",
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PythonPath = ".venv\Scripts\python.exe",
    [string]$ConfigPath = "config.local.json",
    [switch]$RunAsCurrentUser
)

$ErrorActionPreference = "Stop"

$python = Join-Path $ProjectDir $PythonPath
if (-not (Test-Path $python)) {
    throw "Python executable was not found: $python"
}

$config = Join-Path $ProjectDir $ConfigPath
if (-not (Test-Path $config)) {
    throw "Config file was not found: $config"
}

$arguments = "-m autotiangong --config `"$ConfigPath`""
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

if ($RunAsCurrentUser) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Run AutoTiangong campus portal monitor at user logon." `
        -Force | Out-Null
} else {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Run AutoTiangong campus portal monitor at logon." `
        -RunLevel Highest `
        -Force | Out-Null
}

Write-Host "Registered scheduled task: $TaskName"
