[CmdletBinding()]
param(
    [string]$LibraryRoot = '',
    [ValidateRange(1024, 65535)][int]$Port = 8766,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($LibraryRoot)) { $LibraryRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$taskRepoId = '1a3e8840-2f5a-489e-8a4c-27f75bdb5cc0'
$taskRoot = [IO.Path]::GetFullPath($LibraryRoot).TrimEnd('\')
$taskCurrent = Get-Content -LiteralPath (Join-Path $taskRoot 'CURRENT.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($taskCurrent.repo_id -ne $taskRepoId) { throw 'Unrecognized Skills library.' }
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This shared runtime requires Windows x64.' }
$taskUrl = "http://127.0.0.1:$Port"
function Test-Manager {
    try {
        $taskStatus = Invoke-RestMethod -Uri "$taskUrl/api/status" -TimeoutSec 2
        if ($taskStatus.repo_id -ne $taskRepoId -or $taskStatus.test_user_root) { throw 'This port is used by another service.' }
        $taskServiceRoot = [string]$taskStatus.library
        if ($taskServiceRoot.StartsWith('\\?\UNC\')) { $taskServiceRoot = '\\' + $taskServiceRoot.Substring(8) }
        elseif ($taskServiceRoot.StartsWith('\\?\')) { $taskServiceRoot = $taskServiceRoot.Substring(4) }
        if ($taskServiceRoot.TrimEnd('\') -ne $taskRoot) { throw 'This port is managing a different Skills library.' }
        return $true
    } catch [System.Net.WebException] { return $false }
}
if (-not (Test-Manager)) {
    $taskRuntime = Join-Path $taskRoot 'runtime'
    $taskConfig = Get-Content -LiteralPath (Join-Path $taskRoot 'config\runtime.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskManifest = Get-Content -LiteralPath (Join-Path $taskRuntime 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($taskEntry in $taskManifest.files) {
        if ($taskEntry.path -match '(^[/\\]|:|(^|[/\\])\.\.([/\\]|$))') { throw 'Unsafe runtime path.' }
        $taskFile = Join-Path $taskRuntime $taskEntry.path
        if ((Get-FileHash -LiteralPath $taskFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskEntry.sha256) { throw "Shared runtime checksum failed: $($taskEntry.path)" }
    }
    if ($taskConfig.python_folder -notmatch '^python-[0-9.]+-win64$') { throw 'Unexpected runtime folder.' }
    $taskPython = Join-Path $taskRuntime "$($taskConfig.python_folder)\python.exe"
    $taskServer = Join-Path $taskRoot 'scripts\manager_server.py'
    $taskLogRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'NAS-Skills-Manager'
    New-Item -ItemType Directory -Path $taskLogRoot -Force | Out-Null
    $taskLogName = "$taskRepoId-$Port-$(Get-Date -Format yyyyMMddHHmmss)-$([guid]::NewGuid().ToString('N'))"
    $taskLog = Join-Path $taskLogRoot "$taskLogName.log"
    $taskArguments = @('-X', 'utf8', '-B', ('"' + $taskServer + '"'), '--library', ('"' + $taskRoot + '"'), '--port', "$Port")
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLogRoot "$taskLogName.stdout.log") -RedirectStandardError $taskLog -PassThru
    $taskReady = $false
    for ($taskAttempt = 0; $taskAttempt -lt 40; $taskAttempt++) {
        Start-Sleep -Milliseconds 250
        if (Test-Manager) { $taskReady = $true; break }
        if ($taskProcess.HasExited) { break }
    }
    if (-not $taskReady) { throw "Manager did not start. Read $taskLog" }
}
Write-Host "Skills manager ready: $taskUrl"
if (-not $NoBrowser) { Start-Process $taskUrl }
