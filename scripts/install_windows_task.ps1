param(
    [string]$TaskName = "AutoTiangong",
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PythonPath = ".venv\Scripts\python.exe",
    [string]$ConfigPath = "config.local.json",
    [string]$EnvFile = ".env",
    [string]$RunnerPath = "scripts\run_windows_daemon.ps1",
    [string]$LogDir = "logs",
    [int]$IntervalSeconds = 60,
    [switch]$InstallDeps,
    [switch]$ForceLoginOnStart,
    [switch]$StartNow,
    [switch]$RunAsCurrentUser
)

$ErrorActionPreference = "Stop"

function Quote-Arg {
    param([string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

$ProjectDir = (Resolve-Path $ProjectDir).Path
$python = Join-Path $ProjectDir $PythonPath
if ($InstallDeps -and -not (Test-Path $python)) {
    Write-Host "Creating virtual environment at $python"
    py -3 -m venv (Join-Path $ProjectDir ".venv")
}
if (-not (Test-Path $python)) {
    throw "Python executable was not found: $python. Run with -InstallDeps or create .venv first."
}

if ($InstallDeps) {
    & $python -m pip install --upgrade pip
    & $python -m pip install -e $ProjectDir
}

$config = Join-Path $ProjectDir $ConfigPath
if (-not (Test-Path $config)) {
    throw "Config file was not found: $config"
}

$envPath = Join-Path $ProjectDir $EnvFile
if (-not (Test-Path $envPath)) {
    throw "Env file was not found: $envPath"
}

$runner = Join-Path $ProjectDir $RunnerPath
if (-not (Test-Path $runner)) {
    throw "Runner script was not found: $runner"
}

$runnerArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Quote-Arg $runner),
    "-ProjectDir", (Quote-Arg $ProjectDir),
    "-PythonPath", (Quote-Arg $PythonPath),
    "-ConfigPath", (Quote-Arg $ConfigPath),
    "-EnvFile", (Quote-Arg $EnvFile),
    "-LogDir", (Quote-Arg $LogDir),
    "-IntervalSeconds", $IntervalSeconds
)
if ($ForceLoginOnStart) {
    $runnerArgs += "-ForceLoginOnStart"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($runnerArgs -join " ") -WorkingDirectory $ProjectDir
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
Write-Host "Logs will be written under: $(Join-Path $ProjectDir $LogDir)"

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started scheduled task: $TaskName"
}
