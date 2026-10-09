[CmdletBinding()]
param(
    [string]$Query = '',
    [string]$Name = '',
    [string]$Id = '',
    [string]$Category = '',
    [string]$Client = '',
    [ValidateRange(1, 1000)][int]$Top = 10,
    [switch]$IncludeArchives,
    [switch]$IncludeQuarantined,
    [string]$LibraryRoot = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
$taskRepoId = '1a3e8840-2f5a-489e-8a4c-27f75bdb5cc0'
function Get-Sha256([string]$Path) {
    $taskHash = [Security.Cryptography.SHA256]::Create()
    $taskStream = [IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($taskHash.ComputeHash($taskStream))).Replace('-', '').ToLowerInvariant() }
    finally { $taskStream.Dispose(); $taskHash.Dispose() }
}
function Resolve-LibraryPath([string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or $Relative -match '(^[/\\]|:|(^|[/\\])\.\.([/\\]|$))') { throw 'Unsafe catalog path.' }
    $taskRootPath = [IO.Path]::GetFullPath($LibraryRoot).TrimEnd('\') + '\'
    $taskTargetPath = [IO.Path]::GetFullPath((Join-Path $LibraryRoot $Relative))
    if (-not $taskTargetPath.StartsWith($taskRootPath, [StringComparison]::OrdinalIgnoreCase)) { throw 'Catalog path escapes library.' }
    return $taskTargetPath
}
$taskCurrent = Get-Content -LiteralPath (Join-Path $LibraryRoot 'CURRENT.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($taskCurrent.repo_id -ne $taskRepoId -or $taskCurrent.schema -ne 1) { throw 'Unrecognized Skills database.' }
$taskRelease = Resolve-LibraryPath $taskCurrent.release
$taskManifest = Join-Path $taskRelease 'release-manifest.json'
if ((Get-Sha256 $taskManifest) -ne $taskCurrent.release_manifest_sha256) { throw 'Release manifest hash mismatch.' }
$taskCatalogPath = Join-Path $taskRelease 'catalog.json'
$taskReleaseManifest = Get-Content -LiteralPath $taskManifest -Raw -Encoding UTF8 | ConvertFrom-Json
$taskCatalogRecord = @($taskReleaseManifest.files | Where-Object { $_.path -eq 'catalog.json' })
if ($taskCatalogRecord.Count -ne 1 -or (Get-Sha256 $taskCatalogPath) -ne $taskCatalogRecord[0].sha256) { throw 'Catalog hash mismatch.' }
$taskCatalog = @(Get-Content -LiteralPath $taskCatalogPath -Raw -Encoding UTF8 | ConvertFrom-Json)
$taskWords = @($Query.Trim() -split '\s+' | Where-Object { $_ })
$taskMatches = foreach ($taskSkill in $taskCatalog) {
    if (-not $IncludeArchives -and $taskSkill.archive_only) { continue }
    if (-not $IncludeQuarantined -and $taskSkill.status -eq 'quarantined') { continue }
    if ($Name -and $taskSkill.name -ne $Name) { continue }
    if ($Id -and $taskSkill.id -ne $Id) { continue }
    if ($Category -and $taskSkill.category -ne $Category -and $taskSkill.category_label -ne $Category) { continue }
    if ($Client -and -not @($taskSkill.sources | Where-Object { $_.client.IndexOf($Client, [StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count) { continue }
    $taskSearchText = (@($taskSkill.name, $taskSkill.summary, $taskSkill.description, $taskSkill.category_label) + @($taskSkill.dependencies) + @($taskSkill.triggers) + @($taskSkill.keywords)) -join ' '
    $taskAccepted = $true
    foreach ($taskWord in $taskWords) { if ($taskSearchText.IndexOf($taskWord, [StringComparison]::OrdinalIgnoreCase) -lt 0) { $taskAccepted = $false; break } }
    if (-not $taskAccepted) { continue }
    [pscustomobject]@{
        Id = $taskSkill.id; Name = $taskSkill.name; Summary = $taskSkill.summary
        Category = $taskSkill.category_label; Status = $taskSkill.status
        Triggers = @($taskSkill.triggers); Dependencies = @($taskSkill.dependencies)
        EntryPoint = Resolve-LibraryPath $taskSkill.object_path
        Card = Resolve-LibraryPath $taskSkill.card_path
        Variants = @($taskSkill.same_name_variants).Count; Sources = @($taskSkill.sources)
        Issues = @($taskSkill.issues); Snapshot = $taskCurrent.snapshot
    }
}
ConvertTo-Json -InputObject @($taskMatches | Sort-Object @{Expression = { if ($_.Name -eq $Query) { 0 } else { 1 } }}, Name, Id | Select-Object -First $Top) -Depth 15
