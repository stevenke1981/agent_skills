# 管理、同步與復原

## 初次使用

中央庫位於 `\\DVA3221\public_ssd\agent_skills`；Windows 電腦首次執行 `Setup-Client.ps1 -Client <工具>` 即可，後續 Skills 更新無需重新安裝。讀取入口、搜尋腳本與技能包只依賴 SMB 存取；PowerShell 查找使用內建 JSON 功能。

建議用 NAS 原有共享權限設定一位維護者可寫、其他使用者可讀。本次不更改 NAS ACL、帳號或服務。NAS 不在線時中央庫不可用；本機已安裝技能仍可使用，但必須標示未取得中央最新版本。

## 在管理電腦更新

管理專案在 `E:\agent_skills`；Python 3.12+、PyYAML、ripgrep 用於重新盤點封裝，讀取端不需要它們。

```powershell
Set-Location 'E:\agent_skills'
python -X utf8 scripts/discover.py --output .work/discovery.json
python -X utf8 scripts/discover.py --output .work/discovery.json --projects E:\
python -X utf8 scripts/skills_db.py build
python -X utf8 scripts/skills_db.py verify --sources
python -X utf8 scripts/skills_db.py publish
python -X utf8 scripts/skills_db.py verify --library '\\DVA3221\public_ssd\agent_skills'
```

來源是唯讀。忽略 Git internals、套件安裝目錄、建置快取、模型及媒体資料夾；專案磁碟使用深度 6 的有界掃描，完整可見範圍與深度限制寫入 audit。這是已知客戶端與專案 Skill 入口盤點，不是對全磁碟、所有壓縮檔或系統受限目錄的鑑識。

可在其他管理電腦用 `--projects <磁碟或專案>` 擴大盤點，先核對 discovery，再建立快照。多電腦未盤點的私人技能不會憑空出現在這台電腦的 inventory。

發布鎖 `.publish.lock` 防止同時寫入；若前一次異常中止，先查鎖內記載的管理電腦與時間，確認沒有活躍發布作業才將鎖改名留存。不要以強制覆寫繞過鎖。

共享磁碟暫時拒絕更名時，發布工具會短暫等待並有限次重試。持續失敗則保留暫存資料與舊索引；復原暫存封裝前，必須比對本機 manifest 與全部檔案雜湊，不要更改共享權限來繞過錯誤。

封裝會排除憑證檔名與偵測到的常見金鑰內容、外部連結目錄及大於 64 MiB 的單檔；排除原因在 `audit/omissions.json`，原檔留在來源。涉及必要资源的技能會列入待修整。這不是對全部秘密格式的完整安全稽核。

## 改善描述與分類

`config/overrides.json` 以技能名稱對應人工管理欄位，支援 category、summary、triggers、intent、outputs、boundaries、exceptions。描述拆成情境、使用者意圖、任務產物、邊界，來源不足時保持待確認，不以統一模板猜內容。修改後需建新快照发布。

整理不自動改寫客戶端來源的 SKILL.md，也不刪除其他客戶端的 frontmatter。格式缺漏、未完成範本與重要檔案排除會標為 quarantined。新增標準技能可依原有工具的 skill-creator 流程建立，在真實任務驗證後再納入中央庫。

## 復原快照

1. 從 `releases/` 選擇已驗證快照。
2. 執行 `python -X utf8 scripts/skills_db.py verify --library <NAS根目錄> --snapshot <快照名稱>`。
3. 以該快照的 release-manifest.json SHA-256 更新 CURRENT.json，使用同資料夾臨時檔原子替换；同時將該快照 root-index.html 複製為根目錄 index.html。
4. 若要回復管理腳本，讀該快照的 management-source/，核對雜湊後複製，保留原有版本。

不要刪除 objects 或舊 releases。完整讀回驗證才代表 NAS 封裝傳輸正確；它不代表每一種技能的實際工作流程、其他電腦的客戶端熱更新或平台帳號都已驗收。

## Git 備份

管理專案使用本機 Git；資料包以不可變 SHA-256 物件與快照版本管理。Git bundle 存在 NAS 的 versions/，可用 `git clone <bundle> <新資料夾>` 還原管理程式；資料快照由 NAS 的 objects/releases 保留。NAS 自身的另一份異地備份尚未建立。
