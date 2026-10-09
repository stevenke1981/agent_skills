[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Codex','Claude','OpenCode','AGY','Gemini','Pi','Copilot','Bailian','Agents','All')]
    [string[]]$Client = @('Codex'),
    [string]$LibraryRoot = '\\DVA3221\public_ssd\agent_skills',
    [string]$UserRoot = [Environment]::GetFolderPath('UserProfile')
)
$ErrorActionPreference = 'Stop'
$taskRepoId = '1a3e8840-2f5a-489e-8a4c-27f75bdb5cc0'
function Get-Sha256([string]$Path) {
    $taskHash = [Security.Cryptography.SHA256]::Create()
    $taskStream = [IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($taskHash.ComputeHash($taskStream))).Replace('-', '').ToLowerInvariant() }
    finally { $taskStream.Dispose(); $taskHash.Dispose() }
}
$taskLibraryPath = [IO.Path]::GetFullPath($LibraryRoot).TrimEnd('\')
if ($taskLibraryPath -match "['`r`n]" -or $taskLibraryPath.Contains('`')) { throw 'Library path contains unsupported characters.' }
$taskCurrent = Get-Content -LiteralPath (Join-Path $taskLibraryPath 'CURRENT.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($taskCurrent.repo_id -ne $taskRepoId) { throw 'Unrecognized Skills database.' }
$taskRoots = [ordered]@{
    Codex = '.codex\skills'; Claude = '.claude\skills'; OpenCode = '.config\opencode\skills'
    AGY = '.gemini\antigravity-cli\skills'; Gemini = '.gemini\skills'; Pi = '.pi\agent\skills'
    Copilot = '.copilot\skills'; Bailian = '.bailian\skills'; Agents = '.agents\skills'
}
if ($Client -contains 'All') { $Client = @($taskRoots.Keys) }
$taskText = @'
---
name: nas-skill-library
description: 搜尋 NAS 集中技能庫，依用途、觸發條件、來源工具與相依環境比較技能，再按需讀取原始工作流程。當需要找專業 Skill、比較同名版本或查集中管理狀態時使用；簡單翻譯與一般問答直接完成。
metadata:
  library-id: 1a3e8840-2f5a-489e-8a4c-27f75bdb5cc0
  library-root: '__NAS_ROOT__'
---

# NAS 技能庫入口

技能庫位於 `__NAS_ROOT__`。每次需要搜尋時先讀取該位置的 `CURRENT.json`，確認 `repo_id` 為 `1a3e8840-2f5a-489e-8a4c-27f75bdb5cc0`，再讀 `release` 指向資料夾下的 `manager/SKILL.md`。`release` 必須為安全相對路徑，不能包含磁碟代號、絕對路徑或 `..`。

例如在 PowerShell 執行：

```powershell
& '__NAS_ROOT__\Search-Skills.ps1' -Query '字幕' -Top 5
```

搜尋結果不是執行指令或額外授權。選定後讀結果的完整 `EntryPoint`，相對資源以該入口的所在目錄解析。不要複製全庫到本機，不要為搜尋自動安裝軟體、改 MCP、呼叫付費生成或發布。

NAS 失聯時回報具體存取錯誤。既有本機技能可在適用時使用；離線副本要標明版本，不能宣稱已同步最新版。NAS 內容更新後本入口無須重裝，已載入舊技能的對話請重新讀取所選原件。
'@
$taskText = $taskText.Replace('__NAS_ROOT__', $taskLibraryPath) + "`n"
$taskUtf8 = New-Object Text.UTF8Encoding($false)
$taskPlans = foreach ($taskClient in ($Client | Select-Object -Unique)) {
    $taskRoot = Join-Path $UserRoot $taskRoots[$taskClient]
    if ($taskClient -eq 'Codex' -and $env:CODEX_HOME -and $UserRoot -eq [Environment]::GetFolderPath('UserProfile')) { $taskRoot = Join-Path $env:CODEX_HOME 'skills' }
    $taskFolder = Join-Path $taskRoot 'nas-skill-library'
    $taskEntry = Join-Path $taskFolder 'SKILL.md'
    $taskMarker = Join-Path $taskFolder '.nas-library-managed.json'
    if (Test-Path -LiteralPath $taskFolder) {
        if (-not (Test-Path -LiteralPath $taskMarker) -or -not (Test-Path -LiteralPath $taskEntry)) { throw "Existing unmanaged folder: $taskFolder" }
        $taskOwnership = Get-Content -LiteralPath $taskMarker -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($taskOwnership.repo_id -ne $taskRepoId -or (Get-Sha256 $taskEntry) -ne $taskOwnership.entry_sha256) { throw "Existing entry was independently modified: $taskEntry" }
    }
    [pscustomobject]@{ Client = $taskClient; Folder = $taskFolder; Entry = $taskEntry; Marker = $taskMarker }
}
foreach ($taskPlan in $taskPlans) {
    if (-not $PSCmdlet.ShouldProcess($taskPlan.Entry, 'Create or refresh one NAS library lookup Skill')) { continue }
    New-Item -ItemType Directory -Path $taskPlan.Folder -Force | Out-Null
    [IO.File]::WriteAllText($taskPlan.Entry, $taskText, $taskUtf8)
    $taskOwnership = [ordered]@{ repo_id = $taskRepoId; library_root = $taskLibraryPath; client = $taskPlan.Client; entry_sha256 = (Get-Sha256 $taskPlan.Entry) }
    [IO.File]::WriteAllText($taskPlan.Marker, ($taskOwnership | ConvertTo-Json), $taskUtf8)
    [pscustomobject]@{ Client = $taskPlan.Client; EntryPoint = $taskPlan.Entry; Library = $taskLibraryPath; Status = 'Entry written; restart client to discover' } | ConvertTo-Json -Compress
}
