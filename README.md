# NAS 集中 Skills 資料庫

中央資料夾：`\\DVA3221\public_ssd\agent_skills`。從檔案總管開啟 `index.html`，即可搜尋用途、觸發條件及相依工具，篩選分類、來源與歷史版本。介面不需網路服務、外部字型或 CDN。

## 匯入與拖曳安裝介面

雙擊 NAS 中的 **Start-Manager.cmd**，即可開啟收藏與啟用管理頁。貼 GitHub 連結或拖入 ZIP，先保存待審；檢視來源後拖到 **此機 Codex／OpenCode**，確認新技能安裝。拖回收藏區即可停用，拖到回收筒則移除共享收藏並保留還原能力。

同一個啟動檔可在其他 **Windows x64** 電腦直接執行，Python 與管理程式共用 NAS，不需逐台安裝。上方顯示正在操作的電腦；只有小型查找入口寫入該機。詳細流程與權限見 [docs/IMPORT-AND-ACTIVATE.md](docs/IMPORT-AND-ACTIVATE.md)，遊戲技能缺口與下載候選見 [docs/GAPS.md](docs/GAPS.md)。

## 其他電腦只需設定一次

Windows / Codex：雙擊共享資料夾內的 **Setup-Codex.cmd**。只建立一個 `nas-skill-library` 查找入口，之後重啟 Codex；完整技能包留在 NAS。

Windows / Codex + OpenCode：雙擊 **Setup-Codex-OpenCode.cmd**，一次建立兩個工具的入口，再重啟兩個工具。也可在 PowerShell 執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '\\DVA3221\public_ssd\agent_skills\Setup-Client.ps1' -Client Codex,OpenCode"
```

這裡的 ExecutionPolicy 只套用在這次設定程序，不修改電腦的永久政策；不需要系統管理員權限。

其他工具可在 PowerShell 執行：

```powershell
& '\\DVA3221\public_ssd\agent_skills\Setup-Client.ps1' -Client Claude
& '\\DVA3221\public_ssd\agent_skills\Setup-Client.ps1' -Client Codex,Claude,OpenCode,AGY
```

支援 Codex、Claude、OpenCode、Gemini、AGY、Pi、Copilot、Bailian 與共用 Agents 的入口路徑。腳本不覆寫其他技能或模型/MCP 設定；已有同名且非本工具管理的資料夾會停止並指出衝突。它可使用 `-WhatIf` 預覽。

每台電腦需要本來就能存取這個 NAS 共享資料夾。日後發布新的快照，只要重新查找，便會讀取新版。新對話會重新讀入口；進行中已載入的技能請重新讀取。外部軟體、GPU、模型、MCP 與帳號仍由各電腦提供；純文字流程可直接讀取使用。

設定後，在任一工具輸入：「請使用 nas-skill-library，從 NAS 找適合處理字幕的技能。」就會按需查找中央庫；客戶端只看到一個查找入口，不會一次載入幾千個技能。OpenCode 入口位於其[官方支援的全域 Skill 目錄](https://opencode.ai/docs/skills/) `~/.config/opencode/skills/nas-skill-library/SKILL.md`。

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
- `manager-state/`：匯入、收藏、安裝批准與共享回收筒的 JSON 狀態及歷史；不直接更改快照 SQLite。
- `runtime/`：其他 Windows 電腦共用的可攜 Python 與授權資料。

保留使用者提出的五大分類，另加影音與創作、開發與工程、平台與技能管理三類，避免把不同任務硬塞進同一分類。分類及欄位擷取是初始管理資料，人工修訂由 `config/overrides.json` 保留。

完全相同的技能包依 **完整檔案清單與內容** SHA-256 去重；只要 supporting resources 不同就保留不同版本。同名版本保留比較，不自動選成唯一主版本。歷史與未完成範本預設隱藏，可在篩選中查看。

## 版本與維護

一般使用者以 NAS 唯讀權限搜尋即可；維護者建立新快照、逐檔 SHA-256 驗證後再切換 `CURRENT.json`。舊物件與快照保留，可回復。避免讓多台電腦同時直接寫 SQLite；它是每個快照的唯讀索引。

`index.html` 與快照 SQLite 顯示發布時的盤點。之後匯入的收藏、待審與回收筒由管理頁即時合併；總入口的 `Search-Skills.ps1` 也會合併已批准的匯入版本。未批准的新來源不會自動交給客戶端使用。

更新、復原與多電腦使用方式見 [docs/OPERATIONS.md](docs/OPERATIONS.md)，整理原則見 [docs/PRINCIPLES.md](docs/PRINCIPLES.md)。儀表板拖曳排序保存在各電腦瀏覽器，並能匯出 JSON；分類與版本由中央管理者更新。

`manager-state/history/` 只保留最近 500 個修訂。寫入鎖 `manager-state/.write.lock` 超過 10 分鐘未更新會視為當機殘留並自動清除，不必手動刪除。

## 開發與測試

本儲存庫只含管理工具；技能內容、快照與 `runtime/` 都在 NAS，不進版控。換到別的區網時，可設環境變數 `NAS_SKILLS_LIBRARY` 指定共享資料夾，不必改程式；`Setup-Client.ps1` 從共享資料夾執行時會自動使用該資料夾。

```powershell
python -m pip install pyyaml==6.0.3 pytest ruff
python -m ruff check scripts tests
python -m pytest -q tests
```

測試需要 Windows 與 `powershell.exe`；CI 於 `windows-latest`、Python 3.13 執行同一組指令。
