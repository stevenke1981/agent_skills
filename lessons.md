# 維護經驗

## Lesson #1 — 2026-10-09
**Trigger:** NAS 封裝傳輸完成後，SMB 資料夾更名曾暫時回傳 WinError 5；稍後核對內容並更名成功。
**Rule:** 對原子更名採有限次短暫重試；持續失敗時保留暫存內容，逐檔驗證後才復原，完整讀回前不更新 CURRENT。
**Source:** NAS Skills 集中資料庫初次發布。
