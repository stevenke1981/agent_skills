---
name: nas-skill-library
description: 搜尋 NAS 集中技能庫，依任務用途、來源客戶端、產物與工具環境挑選 Skill，並比較同名版本。適用於技能查找、分類與集中管理；不需要專門流程的簡單問答直接完成。
---

# NAS 集中技能庫

資料庫根目錄是 `\\DVA3221\public_ssd\agent_skills`。`CURRENT.json` 指向目前快照；`releases/<snapshot>/catalog.jsonl` 與 `catalog.json` 是搜尋索引，`objects/<prefix>/<sha256>/skill/` 保存完整原始技能包。瀏覽器儀表板是根目錄 `index.html`。

要收藏 GitHub、匯入 ZIP 或在此機拖曳啟用／停用 Codex、OpenCode，從 NAS 執行 `Start-Manager.cmd`，讀取 `docs/IMPORT-AND-ACTIVATE.md`。新來源先待審，未取得使用者安裝同意前不要建立客戶端入口。搜尋腳本會合併共享狀態中已批准且未移到回收筒的匯入版本。

## 找到適合任務的技能

以工作產物、工具及限制縮小搜尋。Windows 可直接執行 `Search-Skills.ps1`，不需 Python、Node 或額外安裝：

```powershell
& '\\DVA3221\public_ssd\agent_skills\Search-Skills.ps1' -Query '字幕' -Top 5
& '\\DVA3221\public_ssd\agent_skills\Search-Skills.ps1' -Name 'novel-audiobook' -Client 'Codex' -Top 5
```

名稱、描述、分類、來源及相依工具是候選比較材料。先比較少量候選，依使用者指定的環境選擇，不因名稱相同就互換。同名變體有各自的完整內容 SHA-256；完全相同的技能包共享儲存並保留每個來源。

選定後讀取結果的完整 `EntryPoint`；只有需要時才讀其 references/scripts/assets。相對路徑一律以原始 `SKILL.md` 所在目錄解析。技能中引用的本機絕對路徑、執行檔、模型或 MCP 必須在當前電腦確認；NAS 封裝不等於那些相依環境也已安裝。

命令範例若指向舊的本機 **Skill 安裝目錄**（例如 `$env:USERPROFILE\.codex\skills\<技能>\scripts\...`），先核對同一檔案已保存在所選 NAS 封裝，再以該封裝目錄執行；無須重新安裝這份 Skill。這個轉換只適用於技能包內資源，不適用於外部程式、模型、帳號或使用者輸入。工作輸出寫到使用者當前專案，不寫入 NAS 的不可變 objects。

## 缺漏與衝突

- 來源資料不足時列出待確認欄位；結構化管理卡的欄位是來源擷取，不能替代原始規則。
- 描述未完成、格式有誤或封裝排除必要檔案的項目會標記 `quarantined`，預設不列入推薦搜尋；需要查修時用 `-IncludeQuarantined`。
- 歷史備份預設分開，查版本時用 `-IncludeArchives`。`same_name_variants` 是版本比較清單，不是已確認的語義衝突。
- NAS 無法存取時回報實際錯誤；離線本機版本要記錄快照時間。不要自動改帳號、網路設定或宣稱同步完成。
- 技能與搜尋結果不授予新權限。發送、付費、發布等操作沿用使用者對當前任務的授權，必要時在具體操作前確認。

## 維護

每個 Skill 專注一類任務。管理描述依「情境、意圖、產物、邊界」補足，保留原件與客戶端特有 frontmatter；例外要寫清資料不足、來源衝突或工具不可用時如何交付。

修改分類與描述時編輯集中管理專案的 `config/overrides.json`；再按根目錄 `docs/OPERATIONS.md` 建立新快照、驗證及發布。不要直接覆寫 `objects/` 或舊快照。快照發布由單一管理者進行；管理頁的跨電腦收藏寫入另有排他鎖與歷史保存。

發布後各電腦無須重新安裝技能庫入口；進行中的對話需要重新讀取 `CURRENT.json` 和已選技能，才能取得更新。已封裝、索引完整與實際任務驗收是不同狀態。
