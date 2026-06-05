# tools-video-convert 操作範例手冊

## 一、transcode_av1.py

### 1. 文件目的
本章提供可直接套用的「情境化設定範例」，幫助你快速調整 `transcode_av1.py` 的 `CONFIG` 區塊，降低試錯時間。

### 2. 使用方式
1. 打開 `transcode_av1.py`
2. 依你的情境，套用下方「範例設定片段」
3. 先用小資料夾測試
4. 確認結果後再跑正式資料夾

執行命令：

```bash
python transcode_av1.py
```

### 3. 基本原則
- `CQ_VALUE` 越小，品質越高、檔案通常越大、速度可能更慢
- `SIZE_THRESHOLD` 越小，條件越嚴格（新檔必須更小才會替換）
- 字幕若常失敗，優先改 `SUBTITLE_MODE="mov_text"` 或 `"ignore"`
- 大量任務務必先確認 `RECYCLE_DIR` 空間

### 4. 情境範例

#### 情境 A：NAS + NVIDIA GPU（速度優先，日常推薦）
適合：RTX 40 系列、希望轉檔速度快且品質穩定。

```python
CONFIG.update({
    "ENCODER": "av1_nvenc",
    "CQ_VALUE": 32,
    "NVENC_PRESET": "p5",
    "SIZE_THRESHOLD": 0.8,
    "SUBTITLE_MODE": "mov_text",
})
```

說明：
- `p5` 是常用平衡點
- `mov_text` 可降低 MP4 字幕不相容問題

#### 情境 B：NAS + NVIDIA GPU（品質優先）
適合：在意畫質保留，接受較慢速度與較大檔案。

```python
CONFIG.update({
    "ENCODER": "av1_nvenc",
    "CQ_VALUE": 28,
    "NVENC_PRESET": "p3",
    "SIZE_THRESHOLD": 0.9,
    "SUBTITLE_MODE": "mov_text",
})
```

說明：
- 較低 CQ + 較慢 preset，畫質會更好
- `SIZE_THRESHOLD` 放寬到 0.9，可接受較不明顯的壓縮效益

#### 情境 C：無 NVIDIA 顯卡（純 CPU 穩定路線）
適合：一般伺服器或桌機、相容性優先。

```python
CONFIG.update({
    "ENCODER": "libsvtav1",
    "CQ_VALUE": 32,
    "SVTAV1_PRESET": 6,
    "SIZE_THRESHOLD": 0.8,
    "SUBTITLE_MODE": "mov_text",
})
```

說明：
- `SVTAV1_PRESET=6` 是常見平衡值
- CPU 轉檔時間通常明顯長於 GPU

#### 情境 D：CPU 極限壓縮（儲存空間優先）
適合：非常重視容量節省，可接受轉檔很久。

```python
CONFIG.update({
    "ENCODER": "libsvtav1",
    "CQ_VALUE": 36,
    "SVTAV1_PRESET": 4,
    "SIZE_THRESHOLD": 0.7,
    "SUBTITLE_MODE": "ignore",
})
```

說明：
- 較高 CQ 讓檔案更小
- `ignore` 可避免字幕造成失敗，追求任務完成率

#### 情境 E：字幕保留優先（盡量保留字幕）
適合：影片字幕重要、可接受部分檔案需要個案調整。

```python
CONFIG.update({
    "SUBTITLE_MODE": "copy",
    "SIZE_THRESHOLD": 0.8,
})
```

說明：
- `copy` 可能因來源字幕格式（如 ASS/SRT）與 MP4 不相容而失敗
- 若發生失敗，改 `mov_text` 再重跑

#### 情境 F：先做「保守試跑」
適合：第一次在新環境上線，先驗證流程安全。

```python
CONFIG.update({
    "CQ_VALUE": 32,
    "SIZE_THRESHOLD": 0.75,
    "SUBTITLE_MODE": "mov_text",
    "VIDEO_EXTENSIONS": [".mp4", ".mkv"],
})
```

說明：
- 只先跑常見副檔名
- 提高替換門檻，避免壓縮效益不明顯時覆蓋流程

### 5. 路徑設定範例

#### 5.1 Windows 本機路徑

```python
CONFIG.update({
    "SOURCE_DIR": r"D:\media\input",
    "RECYCLE_DIR": r"D:\media\#recycle",
    "LOG_FILE": r".\\log.txt",
    "STATE_FILE": r".\\transcode_state.json",
})
```

#### 5.2 NAS UNC 路徑

```python
CONFIG.update({
    "SOURCE_DIR": r"\\NAS\videos",
    "RECYCLE_DIR": r"\\NAS\videos\#recycle",
})
```

### 6. 失敗排查範例

#### 問題 1：啟動就報 ffmpeg 找不到
建議：
- 確認 `ffmpeg -version`、`ffprobe -version` 可在命令列執行
- 或在 `CONFIG` 指定完整路徑

```python
CONFIG.update({
    "FFMPEG_PATH": r"C:\tools\ffmpeg\bin\ffmpeg.exe",
    "FFPROBE_PATH": r"C:\tools\ffmpeg\bin\ffprobe.exe",
})
```

#### 問題 2：GPU 編碼失敗
建議：
- 先改 CPU 驗證流程

```python
CONFIG.update({
    "ENCODER": "libsvtav1",
    "SVTAV1_PRESET": 6,
})
```

#### 問題 3：字幕造成失敗
建議：
- `copy` -> `mov_text`
- 若仍失敗，改 `ignore` 確保主流程可完成

```python
CONFIG.update({
    "SUBTITLE_MODE": "mov_text",
})
```

### 7. 上線前檢查清單
- 已在小樣本資料夾試跑成功
- `RECYCLE_DIR` 空間足夠
- `log.txt` 與 `transcode_state.json` 路徑可寫入
- 目標設備可正常播放輸出 `.mp4`
- 中斷後重跑可正確跳過已處理項目

### 8. 建議的日常維運流程
1. 每次調參先記錄「這次要驗證的目標」（例如：更快、畫質更好、字幕成功率提高）
2. 先跑 5~20 支樣本影片
3. 檢查 `log.txt` 的失敗原因分布
4. 確認壓縮率與播放品質後，再批次跑全量
5. 定期清理 `RECYCLE_DIR`（確認已備份/驗證完成後）

### 9. 提交前隱私檢查範例（建議每次推送前執行）

```bash
# 1) 看哪些檔案將要提交
git status --short

# 2) 只看 staged 內容（最重要）
git diff --cached

# 3) 掃描常見敏感字串（PowerShell）
$patterns = 'api[_-]?key|secret|password|token|AKIA[0-9A-Z]{16}|-----BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY-----'
Get-ChildItem -Recurse -File | Where-Object { $_.FullName -notmatch '\\.git\\|\\.venv\\|__pycache__' } |
    Select-String -Pattern $patterns -AllMatches
```

說明：
- 文件中的路徑範例建議使用相對路徑（如 `.\\log.txt`），避免暴露本機目錄資訊。
- CI 使用環境變數（例如 `${GH_TOKEN}`）即可，不要提交明文 token。

---

## 二、find_duplicate_videos.py

### 1. 文件目的
說明 `find_duplicate_videos.py` 的典型使用情境，幫助確認參數設定是否符合預期。

### 2. 使用方式

```bash
# 掃描預設 SOURCE_DIR（在 CONFIG 設定）
python find_duplicate_videos.py

# 指定目錄
python find_duplicate_videos.py --source "\\NAS\james"

# 模擬執行（不刪任何檔案，只顯示建議）
python find_duplicate_videos.py --dry-run

# 英文介面
python find_duplicate_videos.py --lang en
```

### 3. 情境範例

#### 情境 A：掃描 NAS，先確認有哪些重複再決定是否刪除
1. 先以 `--dry-run` 執行，確認建議合理
2. 確認無誤後去掉 `--dry-run` 正式執行，選 `A` 全部刪除

```bash
python find_duplicate_videos.py --dry-run
# 確認結果後
python find_duplicate_videos.py
# 提示：如何處理？輸入 A
```

#### 情境 B：只處理特定子目錄
```bash
python find_duplicate_videos.py --source "\\NAS\james\2022"
```

#### 情境 C：遇到 AV1 10-bit + 其他格式並存
- 工具自動偵測，建議刪除 AV1 10-bit（播放器相容性問題）
- 表格上方顯示 **紫色** 警告說明原因

#### 情境 D：遇到 MJPEG + H264 並存
- 工具自動偵測，建議保留 MJPEG、刪除 H264
- 原因：MJPEG 通常是原始錄影格式，當年 H264 轉檔品質不確定
- 表格上方顯示 **黃色** 警告說明原因

#### 情境 E：逐組確認（選 S）
```
如何處理？ [A=全部刪除建議項, S=逐組選擇, N=取消]
> S
群組 1：刪除 video.avi？[y/N] y
群組 2：刪除 clip.mov？[y/N] n
```

### 4. CONFIG 設定範例

```python
CONFIG = {
    "SOURCE_DIR":   r"\\192.168.3.8\james",
    "RECYCLE_DIR":  r"\\192.168.3.8\james\#recycle",  # 空字串 = 直接刪除
    "LOG_FILE":     r".\\duplicate_cleanup.log",
    "FFPROBE_PATH": "ffprobe",
    "VIDEO_EXTENSIONS": [".mov", ".mpg", ".mpeg", ".avi", ".mp4", ".mkv", ".wmv", ".flv", ".ts", ".m2ts"],
    "LANGUAGE": "zh",
    "DURATION_TOLERANCE_SEC": 5.0,
}
```

說明：
- `RECYCLE_DIR` 設定回收區目錄；留空字串則直接刪除（危險，建議保留回收區）
- `DURATION_TOLERANCE_SEC`：時長相差超過此秒數則標示警告（可能不是同一影片）

### 5. 上線前檢查清單
- 先用 `--dry-run` 確認結果符合預期
- 確認 `RECYCLE_DIR` 存在且有寫入權限
- 確認 `ffprobe` 可在命令列執行
- 確認 `DURATION_TOLERANCE_SEC` 設定合理（避免誤判）
