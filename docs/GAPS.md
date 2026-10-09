# 遊戲開發技能缺口與候選

盤點基準：2026-10-09 快照 `20261009T103348+0800-i711700`。已經有 Unity、Godot、Unreal、Roblox、Phaser、遊戲設計、素材與音效、網頁遊戲測試等；不將「遊戲開發」整體列為缺少。

比對可用技能的名稱與 description，再檢視命中用途。這是領域專門流程的盤點，不代表沒有通用程式能力，也不是所有產業能力的完整盤點。

| 缺少的專門流程 | 已下載來源 | 收錄數 | 授權／相依 |
| --- | --- | ---: | --- |
| Bevy / Rust ECS | [chrisgliddon/bevy-skills](https://github.com/chrisgliddon/bevy-skills) | 31 | MIT；Bevy 0.19、Rust/Cargo，專門環境依子技能 |
| PixiJS v8 / 2D 渲染 | [pixijs/pixijs-skills](https://github.com/pixijs/pixijs-skills) | 26 | 官方維護、MIT；Node.js、PixiJS v8、瀏覽器 |
| Ren’Py Android 打包 | [yusunz/renpy-android-packager-skill](https://github.com/yusunz/renpy-android-packager-skill) | 1 | MIT；Ren’Py 8.x、Python 3.10+、JDK 21+、Android SDK/RAPT |
| GDevelop 事件／場景 JSON | [adamboothuk/gdevelop-reference](https://github.com/adamboothuk/gdevelop-reference) | 1 | 來源 API 未提供授權資訊；GDevelop、PowerShell |
| Steam Web API | [burkanbogaz/steamworks-api](https://github.com/burkanbogaz/steamworks-api) | 1 | CC0-1.0；網路與對應 API 權限，不在收藏庫保存金鑰 |

這 **60 個技能都先存於 NAS 待審區**，未自動安裝。Bevy 與 PixiJS 建議只啟用 `bevy`、`pixijs` 總入口，依任務讀取子技能；不用一次啟用整包。來源 commit 與完整封裝 SHA-256 可在管理頁「檢視原文」查看。

其他仍缺少可用專門入口：Defold、GameMaker、Steamworks 原生 SDK／發布，以及連線遊戲 rollback netcode。本輪搜尋未找到可直接推薦且已核實的來源。現有 `rollback` 搜尋命中的是部署回復；PixiJS 舊命中是 Three.js 資料視覺化，均不視為對應專門能力。

Ren’Py 候選涵蓋打包；Steam 候選涵蓋 Web API；GDevelop 候選涵蓋 JSON 參考。都不應擴張成完整引擎開發或商店發布能力。

已確認下載來源、固定 commit、封裝格式、授權欄位與 SHA-256，沒有執行第三方腳本。實際工作流程、遊戲引擎與各台電腦的任務驗收仍為 `NOT_RUN`；使用者批准只啟用入口，不代表引擎或帳號相依已安裝。
