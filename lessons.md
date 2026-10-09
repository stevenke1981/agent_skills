# 維護經驗

## Lesson #1 — 2026-10-09
**Trigger:** NAS 封裝傳輸完成後，SMB 資料夾更名曾暫時回傳 WinError 5；稍後核對內容並更名成功。
**Rule:** 對原子更名採有限次短暫重試；持續失敗時保留暫存內容，逐檔驗證後才復原，完整讀回前不更新 CURRENT。
**Source:** NAS Skills 集中資料庫初次發布。

## Lesson #2 — 2026-10-09
**Trigger:** Windows 寫入入口時預設將 LF 轉為 CRLF，造成所有權記錄的 SHA-256 與實際檔案不符。
**Rule:** 對需要逐位元組驗證的入口先生成 UTF-8 bytes，再以同一 bytes 寫入與計算雜湊。
**Source:** 拖曳啟用／停用的行為驗證。

## Lesson #3 — 2026-10-09
**Trigger:** PowerShell 5 的 Join-Path 不接受 Python 的 extended-path 表示；空 JSON 陣列在管線中也可能變成 null。
**Rule:** 對 PowerShell 使用標準 UNC／磁碟路徑，合併索引時略過 null，並驗證尚未批准與已回收的項目不進入預設搜尋。
**Source:** 客戶端總入口搜尋與共享收藏整合測試。
