# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- `find_duplicate_videos.py`: 新增 MJPEG + H264 並存特殊覆蓋規則——保留 MJPEG（原始錄影格式），建議刪除 H264 舊轉檔副本；表格以黃色警告提示原因
- `transcode_av1.py`: 轉檔中即時面板「目前檔案」欄位改顯示完整路徑
- `transcode_av1.py`: 每筆檔案完成後，在面板下方輸出一行結果含完整路徑（`✓` 成功 / `→` 跳過 / `✗` 失敗）

### Fixed
- `transcode_av1.py`: 修正 `av1_nvenc` 缺少 `-b:v 0` 與 `-tune hq`，導致空拍機影片轉檔後無法在電視 / NAS 播放器正常播放的根本原因
- `transcode_av1.py`: 移除 `-profile:v main` 無效參數（此參數在 FFmpeg 7.x 對 av1_nvenc 回傳 `Invalid argument`，導致全批次 rc=-22 失敗）
- `transcode_av1.py`: 新增 `-vf scale=trunc(iw/8)*8:trunc(ih/8)*8`，修正 DJI `clap` atom 造成的 2720×1530（非 8-pixel 對齊）編碼損壞問題

### Changed
- 更新 `readme.md`、`developer_guide.md`、`essential.md`、`examples.md` 以涵蓋雙工具與上述所有變更
- 全面更新所有 Markdown 文件，補充提交前隱私檢查流程與相對路徑建議，避免文件與範例暴露本機環境資訊

---

## [1.1.0] - 2026-05-18

### Added
- `find_duplicate_videos.py`: 新工具——掃描同資料夾內同名但副檔名不同的重複影片，依畫質評分建議刪除版本
  - 品質分 = 解析度像素（W×H）× codec 效率係數（AV1 > HEVC > VP9 > H264 > MPEG4 > WMV > MPEG2）
  - 特殊覆蓋規則：AV1 10-bit 與非 AV1 並存時，建議刪除 AV1 10-bit（播放器相容性）
  - `--dry-run` 模擬執行，不刪任何檔案
  - `--lang zh|en` 雙語介面
  - 互動流程：`A`（全部刪除建議項）/ `S`（逐組確認）/ `N`（取消）
  - 軟刪除至 `RECYCLE_DIR`，留空字串則直接刪除
- `transcode_av1.py`: 新增 `developer_guide.md` 程式架構與函式說明
- `transcode_av1.py`: 新增 `essential.md` 新手開發者指南
- `transcode_av1.py`: 新增 `examples.md` 情境化設定範例手冊
- `filter_log_errors.py`: 錯誤日誌快速篩選工具

### Fixed
- `transcode_av1.py`: 移除 `av1_nvenc` 的 `-profile:v main` 無效參數
- `transcode_av1.py`: 新增 `-vf scale` 修正空拍機 MOV 轉檔時 DJI `clap` atom 造成的寬高對齊問題
- `transcode_av1.py`: 修正 `RECYCLE_DIR` 路徑設定錯誤（`\\NAS\temp\#recycle` → `\\NAS\james\#recycle`）

### Changed
- `readme.md`: 重整為雙工具結構，新增 `find_duplicate_videos.py` 完整說明

---

## [1.0.0] - 2026-05-17

### Added
- `transcode_av1.py`: 初始版本，NAS / 檔案伺服器批次影片轉 AV1 工具
  - 支援 `av1_nvenc`（NVIDIA GPU 硬體編碼）與 `libsvtav1`（CPU 軟體編碼）
  - 安全轉檔流程：輸出暫存檔 → 比較尺寸效益（`SIZE_THRESHOLD`）→ 原檔移至回收區 → 暫存改名為正式輸出
  - 斷點續跑：以 `transcode_state.json` 記錄每檔狀態，中斷後重跑自動跳過已完成項目
  - Rich 即時面板顯示總進度、ETA、fps、speed
  - `--sort` 參數支援三種排序策略：路徑順序 / 由大到小 / 最近修改優先
  - 字幕處理三種模式：`copy` / `mov_text` / `ignore`
  - 掃描結果快取（`scan_cache`），避免大目錄重複掃描
  - `readme.md`：環境需求、安裝步驟、使用說明、常見問題

[Unreleased]: https://gitlab.com/compare/v1.1.0...HEAD
[1.1.0]: https://gitlab.com/compare/v1.0.0...v1.1.0
[1.0.0]: https://gitlab.com/releases/tag/v1.0.0
