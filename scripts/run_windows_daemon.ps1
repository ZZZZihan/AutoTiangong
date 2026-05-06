param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PythonPath = ".venv\Scripts\python.exe",
    [string]$ConfigPath = "config.local.json",
    [string]$EnvFile = ".env",
    [string]$LogDir = "logs",
    [int]$IntervalSeconds = 60,
    [switch]$ForceLoginOnStart
)

$ErrorActionPreference = "Stop"

function Resolve-InProject {
    param([string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }
    return (Join-Path $ProjectDir $Path)
}

function Invoke-AutoTiangong {
    param(
        [string]$Python,
        [string[]]$Arguments,
        [string]$LogFile
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] > $Python $($Arguments -join ' ')" | Tee-Object -FilePath $LogFile -Append
    & $Python @Arguments 2>&1 | Tee-Object -FilePath $LogFile -Append
    return $LASTEXITCODE
}

$ProjectDir = (Resolve-Path $ProjectDir).Path
Set-Location $ProjectDir

$python = Resolve-InProject $PythonPath
$config = Resolve-InProject $ConfigPath
$envPath = Resolve-InProject $EnvFile
$logDirPath = Resolve-InProject $LogDir

if (-not (Test-Path $python)) {
    throw "Python executable was not found: $python"
}
if (-not (Test-Path $config)) {
    throw "Config file was not found: $config"
}
if (-not (Test-Path $envPath)) {
    throw "Env file was not found: $envPath"
}
if (-not (Test-Path $logDirPath)) {
    New-Item -ItemType Directory -Path $logDirPath | Out-Null
}

$logFile = Join-Path $logDirPath "autotiangong.log"
$mainArgs = @(
    "-m", "autotiangong",
    "--config", $ConfigPath,
    "--env-file", $EnvFile,
    "--interval", [string]$IntervalSeconds
)

if ($ForceLoginOnStart) {
    $forceArgs = @(
        "-m", "autotiangong",
        "--config", $ConfigPath,
        "--env-file", $EnvFile,
        "--once",
        "--force-login",
        "--auto-switch",
        "--verbose"
    )
    $forceExit = Invoke-AutoTiangong -Python $python -Arguments $forceArgs -LogFile $logFile
    "[$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")] force-login exit code: $forceExit" |
        Tee-Object -FilePath $logFile -Append
}

$exitCode = Invoke-AutoTiangong -Python $python -Arguments $mainArgs -LogFile $logFile
exit $exitCode
