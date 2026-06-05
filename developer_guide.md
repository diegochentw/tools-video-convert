# transcode_av1.py Developer Guide

## 1. 程式定位
`transcode_av1.py` 是單檔 Python 腳本，負責批次轉碼與檔案生命週期管理。設計重點是：
- 可觀測（Rich Live 面板 + 每檔 console 輸出 + log）
- 可回復（state 檔 + 斷點續跑）
- 資料安全（暫存、效益判斷、回收區）

## 2. 高層流程
1. 驗證 `SOURCE_DIR` 與 ffmpeg/ffprobe 可用性
2. 初始化 logger 與 state
3. 掃描所有影片檔案（含掃描快取）
4. 濾除已成功或已存在對應 `.mp4` 的檔案
5. 逐檔呼叫 `process_one()`；每檔完成後在 console 輸出一行結果（含完整路徑與 ✓/→/✗）
6. 每檔結果立刻寫回 state（降低中斷損失）
7. 任務結束輸出統計

## 3. 主要模組與函式
- `setup_logger(log_path)`：建立檔案 logger
- `load_state(state_path)` / `save_state(state_path, state)`：續傳狀態載入/原子寫入
- `scan_videos(source_dir, extensions, state, cache_hours, force_rescan)`：遞迴掃描來源影片，支援快取
- `build_pending_videos(all_videos, processed_map)`：依狀態篩選待處理清單
- `sort_pending_videos(videos, sort_mode)`：可插拔排序（路徑/大小/最近上傳）
- `get_video_info(video_path, ffprobe)`：取得 codec、duration、audio_codec
- `build_ffmpeg_cmd(input_path, output_path, config, audio_codec)`：建構 ffmpeg 指令
- `parse_progress_line(line, state)`：解析 `-progress pipe:1` key/value
- `make_panel(snap)`：建立 Rich 面板；`panel_current` 欄位顯示完整路徑
- `safe_move_to_recycle(src, source_root, recycle_root, logger)`：移原檔到回收區，保留相對路徑
- `process_one(...)`：單檔完整處理（核心）
- `main()`：主流程與統計管理

## 4. 資料結構
### 4.1 CONFIG
集中所有可調參數，含路徑、編碼器、品質、字幕策略與掃描副檔名。

### 4.2 State 檔（JSON）
結構概念：

```json
{
  "processed": {
    "\\\\nas\\james\\video.mkv": {
      "status": "success|skipped|failed",
      "reason": "文字原因",
      "bytes_saved": 12345,
      "time": "ISO8601"
    }
  },
  "scan_cache": {
    "source_dir": "...",
    "scanned_at": "ISO8601",
    "files": ["path1", "path2"]
  }
}
```

說明：
- key 使用小寫路徑字串（Windows 不分大小寫）
- 成功/跳過/失敗都會記錄，避免重複處理與方便追蹤

## 5. 轉檔策略與安全機制
`process_one()` 的關鍵保護邏輯：
1. 先寫暫存檔 `*_tmp.mp4`
2. ffmpeg 失敗或暫存為空 => 刪暫存並回傳 `failed`
3. 計算 `ratio = new_size / original_size`
4. 若 `ratio > SIZE_THRESHOLD` => 視為不具效益，刪暫存並 `skipped`
5. 若具效益：
   - 原檔移動到回收區
   - 暫存改名為正式輸出
   - 回傳 `success` 與節省空間

這可降低「輸出失敗但原檔已被覆蓋」的風險。

## 6. Console 輸出行為
每個檔案完成後，會在 Rich Live 面板下方輸出一行結果（rich 自動暫停面板再輸出，不會互相干擾）：

```
  ✓ \\nas\james\dir\file.mp4        ← 成功（綠色）
  → \\nas\james\dir\already.avi     ← 跳過（灰色）
  ✗ \\nas\james\dir\broken.mov      ← 失敗（紅色）
```

Live 面板「目前檔案」欄位也顯示完整路徑，方便長時間跑批次時快速確認進度。

## 7. 字幕處理細節
- `ignore`：`-sn`
- `mov_text`：`-c:s mov_text`
- `copy`：`-c:s copy`

注意：在 MP4 容器中，某些字幕格式不可直接 copy；若碰到轉檔失敗，優先檢查此處。

## 8. 已知風險與建議改進
- 目前無單元測試；建議拆出可測函式並補 `pytest`
- 長路徑/權限問題可能造成搬移失敗；建議補更明確錯誤分類
- 同檔名衝突已有備份策略，但可再加入更完整告警

## 9. 擴充方向
- 支援 JSON/YAML 設定檔而非直接改 Python 程式
- 將 state 管理封裝為獨立類別
- 新增 dry-run 模式（只估算、不做實際搬移）
- 新增 retry 與錯誤類型統計

## 10. 除錯建議
- 先看 `log.txt` 中的 `[失敗]` 與 returncode
- 抽出該檔案 ffmpeg 指令做單檔重跑
- 字幕報錯時先切 `SUBTITLE_MODE="ignore"` 驗證主流程
- 若懷疑 state 異常，可備份後重建 state 檔

## 11. 提交前檢查建議
- 檢查 `git diff --cached`，確認未提交敏感資訊（token、password、私鑰）。
- 確認 `.gitignore` 覆蓋快取與執行輸出（`__pycache__/`、`.venv/`、`log.txt`、`transcode_state.json`）。
- 文件範例盡量使用相對路徑，避免提交個人環境資訊。
