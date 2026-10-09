# NAS 集中 Skills 資料庫

中央資料夾：`\\DVA3221\public_ssd\agent_skills`。從檔案總管開啟 `index.html`，即可搜尋用途、觸發條件及相依工具，篩選分類、來源與歷史版本。介面不需網路服務、外部字型或 CDN。

## 其他電腦只需設定一次

Windows / Codex：雙擊共享資料夾內的 **Setup-Codex.cmd**。只建立一個 `nas-skill-library` 查找入口，之後重啟 Codex；完整技能包留在 NAS。

其他工具可在 PowerShell 執行：

```powershell
& '\\DVA3221\public_ssd\agent_skills\Setup-Client.ps1' -Client Claude
& '\\DVA3221\public_ssd\agent_skills\Setup-Client.ps1' -Client Codex,Claude,OpenCode,AGY
```

支援 Codex、Claude、OpenCode、Gemini、AGY、Pi、Copilot、Bailian 與共用 Agents 的入口路徑。腳本不覆寫其他技能或模型/MCP 設定；已有同名且非本工具管理的資料夾會停止並指出衝突。它可使用 `-WhatIf` 預覽。

每台電腦需要本來就能存取這個 NAS 共享資料夾。日後發布新的快照，只要重新查找，便會讀取新版。新對話會重新讀入口；進行中已載入的技能請重新讀取。外部軟體、GPU、模型、MCP 與帳號仍由各電腦提供；純文字流程可直接讀取使用。

## 搜尋與內容

```powershell
& '\\DVA3221\public_ssd\agent_skills\Search-Skills.ps1' -Query 'FFmpeg 字幕' -Top 5
& '\\DVA3221\public_ssd\agent_skills\Search-Skills.ps1' -Name 'novel-audiobook' -Client Codex
```

- `CURRENT.json`：目前快照指標。
- `releases/<snapshot>/catalog.jsonl`、`catalog.json`：完整索引。
- `releases/<snapshot>/inventory.csv`：可在 Excel 開啟的 UTF-8 清單。
- `releases/<snapshot>/skills.sqlite`：SQLite / FTS5 唯讀資料庫；中文可用 `LIKE` 或搜尋腳本的子字串搜尋。
- `releases/<snapshot>/cards/`：每個技能的情境、意圖、產物、邊界、例外、依賴與改善清單。
- `objects/<prefix>/<sha256>/skill/`：原始 `SKILL.md` 與支援資源，不執行來源腳本。
- `releases/<snapshot>/audit/`：掃描範圍、失效舊路徑、封裝排除、同名版本及待改善清單。
- `versions/`：管理專案的 Git bundle，與資料快照分開保存。

保留使用者提出的五大分類，另加影音與創作、開發與工程、平台與技能管理三類，避免把不同任務硬塞進同一分類。分類及欄位擷取是初始管理資料，人工修訂由 `config/overrides.json` 保留。

完全相同的技能包依 **完整檔案清單與內容** SHA-256 去重；只要 supporting resources 不同就保留不同版本。同名版本保留比較，不自動選成唯一主版本。歷史與未完成範本預設隱藏，可在篩選中查看。

## 版本與維護

一般使用者以 NAS 唯讀權限搜尋即可；維護者建立新快照、逐檔 SHA-256 驗證後再切換 `CURRENT.json`。舊物件與快照保留，可回復。避免讓多台電腦同時直接寫 SQLite；它是每個快照的唯讀索引。

更新、復原與多電腦使用方式見 [docs/OPERATIONS.md](docs/OPERATIONS.md)，整理原則見 [docs/PRINCIPLES.md](docs/PRINCIPLES.md)。儀表板拖曳排序保存在各電腦瀏覽器，並能匯出 JSON；分類與版本由中央管理者更新。
