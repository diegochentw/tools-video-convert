# tools-video-convert

本專案包含兩支獨立的影片工具腳本，可搭配使用，適合 NAS / 檔案伺服器場景。

---

## transcode_av1.py

### 1. 專案說明
`transcode_av1.py` 是一支用於 NAS/檔案伺服器場景的影片批次轉檔腳本，會遞迴掃描來源資料夾中的影片，並將影片轉為 AV1 的 `.mp4`。

此腳本特點：
- 支援兩種編碼模式：
  - `av1_nvenc`：NVIDIA GPU 硬體編碼（速度快）
  - `libsvtav1`：CPU 軟體編碼（相容性高）
- 安全轉檔流程：
  1. 先輸出暫存檔 `*_tmp.mp4`
  2. 比較檔案大小，判斷是否具壓縮效益
  3. 有效益才將原檔移到回收區
  4. 最後把暫存檔改名為正式 `.mp4`
- 具備中斷續傳能力：
  - 使用 `transcode_state.json` 記錄每檔處理結果
  - 若已成功或已存在對應 `.mp4`，下次會自動跳過
- 提供 Rich 即時面板與 `log.txt` 完整記錄，方便長時間批次任務觀察與追蹤。

### 2. 環境需求
- Python 3.9+
- Python 套件：`rich`
- 系統 PATH 可執行：`ffmpeg`、`ffprobe`
- 若使用 `av1_nvenc`，需支援 AV1 編碼的 NVIDIA 顯卡與相容驅動

安裝套件：

```bash
pip install rich
```

### 3. 使用說明

#### 3.1 設定參數
請先編輯 `transcode_av1.py` 內的 `CONFIG` 區塊，至少確認以下項目：
- `SOURCE_DIR`：來源資料夾（會遞迴掃描）
- `RECYCLE_DIR`：原檔軟刪除移動位置
- `LOG_FILE`：日誌檔路徑
- `STATE_FILE`：狀態檔路徑
- `ENCODER`：`av1_nvenc` 或 `libsvtav1`
- `CQ_VALUE`：品質/壓縮平衡
- `SIZE_THRESHOLD`：效益門檻（新檔/原檔比例）
- `SUBTITLE_MODE`：`copy` / `mov_text` / `ignore`

#### 3.2 執行
在專案根目錄執行：

```bash
python transcode_av1.py
```

可指定轉檔排序策略：

```bash
# 1 = 先轉大檔（依檔案大小由大到小）
python transcode_av1.py --sort 1

# 2 = 先轉最近上傳/修改（依時間由新到舊）
python transcode_av1.py --sort 2
```

#### 3.3 觀察結果
- 主控台顯示即時進度面板（成功/跳過/失敗、ETA、目前檔案速度等），面板「目前檔案」欄位顯示**完整路徑**，方便確認正在處理哪一個檔案。
- 每個檔案處理完成後，console 會在面板下方輸出一行結果：
  - `✓ /完整/路徑/file.mp4`（成功，綠色）
  - `→ /完整/路徑/file.avi`（跳過，灰色）
  - `✗ /完整/路徑/file.mov`（失敗，紅色）
- 處理細節可於 `log.txt` 查看
- 每檔狀態可於 `transcode_state.json` 查看

### 4. 注意事項
- 字幕與 MP4 相容性：
  - `SUBTITLE_MODE="copy"` 在來源字幕為 SRT/ASS 時可能失敗
  - 常見做法是改成 `mov_text` 或 `ignore`
- `SIZE_THRESHOLD` 的意義：
  - 例如 `0.8` 代表「新檔需小於原檔 80% 才算有效益」
  - 若不達標，暫存檔會被刪除，原檔保留
- 本程式會對檔案做實際搬移與改名：
  - 建議先在小資料夾做測試
  - 建議先確認回收區容量足夠
- 中斷處理：
  - 按 `Ctrl+C` 可安全中止
  - 下次執行會依狀態檔續跑

### 5. 常見問題
- 問：找不到 `ffmpeg` 或 `ffprobe`？
  - 答：請確認已安裝並加入系統 PATH，或在 `CONFIG` 指定完整路徑。
- 問：GPU 編碼失敗？
  - 答：改用 `libsvtav1` 測試，並檢查顯卡型號與驅動版本。
- 問：轉完檔案反而變大？
  - 答：可提高 `CQ_VALUE`（數值更大）或調整 `SIZE_THRESHOLD`。

---

## find_duplicate_videos.py

### 1. 工具說明
`find_duplicate_videos.py` 掃描來源目錄，找出**同一資料夾內、檔名相同但副檔名不同**的影片，用 `ffprobe` 比對畫質，列出建議後詢問是否批次刪除較差的版本。

適用情境：
- 過去用轉檔軟體轉了新格式，但忘記刪除原始檔
- 想找出重複影片中應保留哪一個版本

### 2. 環境需求
- Python 3.9+、`rich`
- 系統 PATH 可執行：`ffprobe`

```bash
pip install rich
```

### 3. 使用說明

```bash
python find_duplicate_videos.py [--source <路徑>] [--dry-run] [--lang zh|en]
```

- `--dry-run`：模擬執行，只列出建議，不真正刪除
- `--source`：覆蓋 CONFIG 中的來源目錄

### 4. 畫質判斷邏輯
品質分 = 解析度像素（W×H）× codec 效率系數（1.0～2.0），**不以檔案大小為準**，避免因舊版轉檔軟體效率差而誤判。

Codec 效率排序（高→低）：AV1 > HEVC > VP9 > H264 > MPEG4 > WMV > MPEG2

### 5. 特殊覆蓋規則

| 情境 | 行為 | 原因 |
|------|------|------|
| 群組內有 AV1 10-bit 與非 AV1 並存 | 建議刪除 AV1 10-bit | 播放器相容性問題 |
| 群組內有 MJPEG 與 H264 並存 | 建議保留 MJPEG，刪除 H264 | MJPEG 通常為原始錄影格式；當年 H264 轉檔品質不確定 |

觸發特殊規則時，表格會顯示說明訊息，品質分欄位顯示 `—` 避免誤導。

### 6. 互動流程
分析完成後顯示結果表格，並詢問：
- `A`：全部刪除有「刪除」建議的項目
- `S`：逐組確認
- `N`：取消，不刪除任何檔案

刪除前會先移到 `RECYCLE_DIR`（軟刪除），若 `RECYCLE_DIR` 設為空字串則直接刪除。

---

## 提交前隱私檢查（GitHub / GitLab）

建議每次推送前都執行以下檢查：
- 確認 `.gitignore` 已包含：`__pycache__/`、`.venv/`、`log.txt`、`transcode_state.json`
- 確認未追蹤或待提交檔案中，沒有明文密鑰（token、password、private key）
- 文件與程式範例避免使用個人本機絕對路徑（例如 `D:\\你的帳號\\...`）

本專案目前建議：
- 程式內預設日誌與狀態檔路徑使用「程式所在目錄推導」
- 文件範例使用相對路徑（例如 `.\\log.txt`）
