#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS 影片批次 AV1 轉檔工具 / NAS Video Batch AV1 Transcoder
============================================================
功能：遞迴掃描指定資料夾，將主流影片格式批次轉為 AV1 (10-bit) 的 .mp4
- NVIDIA GPU (av1_nvenc) 或 CPU (libsvtav1) 編碼
- 安全流程：暫存檔 -> 效益分析 -> 軟刪除回收 -> 改名落地
- 掃描快取：大型 NAS 第二次執行可跳過耗時掃描，直接續傳
- 多語系 UI：zh / en / es / ja
- 續傳：狀態檔記錄每檔結果，重新執行自動跳過已完成項目

執行需求
- Python 3.9+、pip install rich
- 系統 PATH 需有 ffmpeg / ffprobe (建議 7.x+)
- NVIDIA 用戶需 R530+ 驅動 (RTX 40 系列起支援 AV1 硬體編碼)

用法
  python transcode_av1.py [--lang zh|en|es|ja] [--rescan] [--reset-failed]
"""

import os
import sys
import json
import shutil
import subprocess
import re
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Callable

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
except ImportError:
    print("Error / 錯誤: pip install rich")
    sys.exit(1)


# ============================================================
# 使用者設定區（請依環境修改）
# ============================================================
CONFIG = {
    # --- 路徑設定 ---
    "SOURCE_DIR":   r"\\192.168.3.8\james",
    "RECYCLE_DIR":  r"\\192.168.3.8\james\#recycle",
    "LOG_FILE":     str(Path(__file__).resolve().parent / "log.txt"),
    "STATE_FILE":   str(Path(__file__).resolve().parent / "transcode_state.json"),

    # --- 編碼器設定 ---
    # "av1_nvenc": NVIDIA GPU 硬體編碼（RTX 40 系列以上推薦）
    # "libsvtav1": CPU 軟體編碼
    "ENCODER": "av1_nvenc",
    "CQ_VALUE": 32,
    "NVENC_PRESET": "p5",   # p1(最佳品質) ~ p7(最快)
    "SVTAV1_PRESET": 6,     # 0(最慢) ~ 13(最快)
    "BIT_DEPTH": 8,         # 8 或 10（10-bit 播放器相容性較差）

    # --- 防呆設定 ---
    "SIZE_THRESHOLD": 0.8,          # 新檔/原檔 超過此比例視為不具效益
    "EARLY_ABORT_START_PCT": 20,    # 超過此進度才開始預估；設 100 可停用

    # --- 字幕處理 ---
    # "copy" / "mov_text" / "ignore"
    # "ignore" is recommended for drone/phone footage (avoids GPS/telemetry track errors)
    "SUBTITLE_MODE": "ignore",

    # --- 掃描設定 ---
    "VIDEO_EXTENSIONS": [".mov", ".mpg", ".mpeg", ".avi", ".mp4", ".mkv", ".wmv", ".flv"],

    # --- FFmpeg 路徑 ---
    "FFMPEG_PATH":  "ffmpeg",
    "FFPROBE_PATH": "ffprobe",

    # --- 語言設定 ---
    # "zh"=中文  "en"=English  "es"=Español  "ja"=日本語
    "LANGUAGE": "en",

    # --- 掃描快取 ---
    # 快取有效時數（0=停用，每次重新掃描；建議設 8~24 加速續傳）
    "SCAN_CACHE_HOURS": 12,
}
# ============================================================


# ============================================================
# 多語系字串
# ============================================================
_STRINGS: Dict[str, Dict[str, str]] = {
    "zh": {
        "source_not_found":    "來源資料夾不存在: {path}",
        "ffmpeg_not_found":    "找不到 {name}：{err}",
        "ffmpeg_bad_rc":       "{name} 無法執行：returncode={rc}",
        "state_corrupt":       "狀態檔損壞，將重新建立",
        "save_state_failed":   "儲存狀態檔失敗: {err}",
        "scanning":            "正在掃描 [{count} 個]：{dir}",
        "scan_done":           "掃描完成：找到 {count} 個影片",
        "cache_hit":           "使用掃描快取（{count} 個檔案，快取於 {time}）",
        "cache_expired":       "快取已過期，重新掃描...",
        "cache_saved":         "掃描結果已快取（{count} 個檔案）",
        "no_pending":          "無待處理檔案（掃描 {total}，跳過 {skipped}）",
        "pending_info":        "掃描 {total} 個，跳過 {skipped}，待處理 {pending}",
        "interrupted":         "使用者中斷，已儲存進度。下次執行將自動續傳。",
        "all_done":            "全部完成！",
        "success_label":       "成功",
        "skipped_label":       "跳過",
        "failed_label":        "失敗",
        "total_saved":         "累計節省空間：",
        "see_log":             "詳細日誌：{path}",
        "reset_failed_done":   "已清除 {count} 筆失敗記錄，下次執行將重試。",
        "panel_title":         "NAS 影片批次 AV1 轉檔",
        "panel_total":         "總檔案數",
        "panel_done_rem":      "已處理 / 剩餘",
        "panel_stats":         "成功 / 跳過 / 失敗",
        "panel_saved":         "累計節省空間",
        "panel_elapsed":       "已運行時間",
        "panel_eta":           "預估剩餘時間",
        "panel_current":       "目前檔案",
        "panel_progress":      "當前進度",
        "panel_ratio":         "預估壓縮率",
        "panel_threshold":     "門檻",
        "hdr_source":          "來源",
        "hdr_recycle":         "回收區",
        "hdr_encoder":         "編碼器",
        "hdr_log":             "日誌檔",
        "hdr_lang":            "語言",
        "hdr_cache":           "掃描快取",
        "cache_hours_fmt":     "{h}h（使用 --rescan 強制重新掃描）",
        "cache_off":           "停用（每次重新掃描）",
        "reason_mp4_exists":   "對應 .mp4 已存在",
        "reason_is_av1":       "來源已為 AV1，無需重複轉檔",
        "reason_zero_byte":    "原檔大小為 0 byte",
        "reason_read_failed":  "無法讀取原檔大小: {err}",
        "reason_start_failed": "啟動 ffmpeg 失敗: {err}",
        "reason_early_abort":  "預判不具效益（{pct:.0f}% 時預估壓縮率 {ratio:.1%} > 門檻 {thr:.0%}）",
        "reason_failed":       "轉檔失敗 (rc={rc}): {err}",
        "reason_no_benefit":   "不具效益（{ratio:.2%} > 門檻 {thr:.0%}，原 {orig} -> 新 {new}）",
        "reason_recycle_fail": "原檔移至回收區失敗，已保留暫存檔以防遺失",
        "reason_rename_fail":  "暫存檔改名失敗: {err}",
        "reason_success":      "原檔 {orig} -> 新檔 {new}（壓縮率 {ratio:.2%}，節省 {saved}）",
        "log_start":           "=== 開始批次轉檔 來源={src} 編碼器={enc} CQ={cq} 門檻={thr} ===",
        "log_scan_done":       "掃描完成: 總計 {total}，跳過 {skipped}，待處理 {pending}",
        "log_no_pending":      "完成：無待處理檔案。掃描={total} 跳過={skipped}",
        "log_end":             "=== 結束: 成功 {s} / 跳過 {sk} / 失敗 {f}，節省 {saved} ===",
        "recycle_fail":        "移至回收區失敗: {src} -> {dst}: {err}",
        "conflict_backup":     "目標已存在，備份為: {path}",
        "progress_err":        "讀取進度時例外: {err}",
        "unexpected":          "未預期例外: {err}",
        "log_success":         "[成功]",
        "log_skipped":         "[跳過]",
        "log_failed":          "[失敗]",
    },
    "en": {
        "source_not_found":    "Source directory not found: {path}",
        "ffmpeg_not_found":    "{name} not found: {err}",
        "ffmpeg_bad_rc":       "{name} failed: returncode={rc}",
        "state_corrupt":       "State file corrupted, rebuilding",
        "save_state_failed":   "Failed to save state: {err}",
        "scanning":            "Scanning [{count}]: {dir}",
        "scan_done":           "Scan complete: {count} video files found",
        "cache_hit":           "Using scan cache ({count} files, cached at {time})",
        "cache_expired":       "Cache expired, rescanning...",
        "cache_saved":         "Scan results cached ({count} files)",
        "no_pending":          "No files to process (scanned {total}, skipped {skipped})",
        "pending_info":        "Scanned {total}, skipped {skipped}, pending {pending}",
        "interrupted":         "Interrupted by user. Progress saved. Next run will resume.",
        "all_done":            "All done!",
        "success_label":       "Success",
        "skipped_label":       "Skipped",
        "failed_label":        "Failed",
        "total_saved":         "Total space saved:",
        "see_log":             "Log file: {path}",
        "reset_failed_done":   "Cleared {count} failed entries. They will be retried next run.",
        "panel_title":         "NAS Video Batch AV1 Transcoder",
        "panel_total":         "Total files",
        "panel_done_rem":      "Done / Remaining",
        "panel_stats":         "Success / Skipped / Failed",
        "panel_saved":         "Space saved",
        "panel_elapsed":       "Elapsed",
        "panel_eta":           "ETA",
        "panel_current":       "Current file",
        "panel_progress":      "Progress",
        "panel_ratio":         "Projected ratio",
        "panel_threshold":     "threshold",
        "hdr_source":          "Source",
        "hdr_recycle":         "Recycle",
        "hdr_encoder":         "Encoder",
        "hdr_log":             "Log",
        "hdr_lang":            "Language",
        "hdr_cache":           "Scan cache",
        "cache_hours_fmt":     "{h}h (use --rescan to force fresh scan)",
        "cache_off":           "Disabled (always rescan)",
        "reason_mp4_exists":   "Corresponding .mp4 already exists",
        "reason_is_av1":       "Source is already AV1, skipping",
        "reason_zero_byte":    "Source file is 0 bytes",
        "reason_read_failed":  "Cannot read source file size: {err}",
        "reason_start_failed": "Failed to start ffmpeg: {err}",
        "reason_early_abort":  "Early abort ({pct:.0f}% done, projected {ratio:.1%} > threshold {thr:.0%})",
        "reason_failed":       "Transcode failed (rc={rc}): {err}",
        "reason_no_benefit":   "No benefit ({ratio:.2%} > threshold {thr:.0%}, {orig} -> {new})",
        "reason_recycle_fail": "Failed to move original to recycle bin, temp file kept",
        "reason_rename_fail":  "Failed to rename temp file: {err}",
        "reason_success":      "{orig} -> {new} (ratio {ratio:.2%}, saved {saved})",
        "log_start":           "=== Start src={src} encoder={enc} CQ={cq} threshold={thr} ===",
        "log_scan_done":       "Scan done: total {total}, skipped {skipped}, pending {pending}",
        "log_no_pending":      "Done: nothing to process. scanned={total} skipped={skipped}",
        "log_end":             "=== Done: success {s} / skipped {sk} / failed {f}, saved {saved} ===",
        "recycle_fail":        "Move to recycle failed: {src} -> {dst}: {err}",
        "conflict_backup":     "Target exists, backed up to: {path}",
        "progress_err":        "Exception reading progress: {err}",
        "unexpected":          "Unexpected exception: {err}",
        "log_success":         "[success]",
        "log_skipped":         "[skipped]",
        "log_failed":          "[failed]",
    },
    "es": {
        "source_not_found":    "Directorio fuente no encontrado: {path}",
        "ffmpeg_not_found":    "{name} no encontrado: {err}",
        "ffmpeg_bad_rc":       "{name} falló: returncode={rc}",
        "state_corrupt":       "Archivo de estado corrupto, reconstruyendo",
        "save_state_failed":   "Error al guardar estado: {err}",
        "scanning":            "Escaneando [{count}]: {dir}",
        "scan_done":           "Escaneo completo: {count} archivos de video",
        "cache_hit":           "Usando caché ({count} archivos, en caché a las {time})",
        "cache_expired":       "Caché expirado, reescaneando...",
        "cache_saved":         "Resultados en caché ({count} archivos)",
        "no_pending":          "Sin archivos pendientes (escaneados {total}, omitidos {skipped})",
        "pending_info":        "Escaneados {total}, omitidos {skipped}, pendientes {pending}",
        "interrupted":         "Interrumpido. Progreso guardado. La próxima ejecución reanudará.",
        "all_done":            "¡Todo listo!",
        "success_label":       "Éxito",
        "skipped_label":       "Omitido",
        "failed_label":        "Fallido",
        "total_saved":         "Espacio ahorrado:",
        "see_log":             "Registro: {path}",
        "reset_failed_done":   "Se eliminaron {count} entradas fallidas. Se reintentarán.",
        "panel_title":         "Transcodificador AV1 por Lotes",
        "panel_total":         "Total archivos",
        "panel_done_rem":      "Hecho / Restante",
        "panel_stats":         "Éxito / Omitido / Fallido",
        "panel_saved":         "Espacio ahorrado",
        "panel_elapsed":       "Transcurrido",
        "panel_eta":           "Tiempo restante",
        "panel_current":       "Archivo actual",
        "panel_progress":      "Progreso",
        "panel_ratio":         "Ratio proyectado",
        "panel_threshold":     "umbral",
        "hdr_source":          "Fuente",
        "hdr_recycle":         "Reciclaje",
        "hdr_encoder":         "Codificador",
        "hdr_log":             "Registro",
        "hdr_lang":            "Idioma",
        "hdr_cache":           "Caché escaneo",
        "cache_hours_fmt":     "{h}h (use --rescan para forzar nuevo escaneo)",
        "cache_off":           "Desactivado (siempre reescanear)",
        "reason_mp4_exists":   "El .mp4 correspondiente ya existe",
        "reason_is_av1":       "La fuente ya es AV1, omitiendo",
        "reason_zero_byte":    "El archivo fuente tiene 0 bytes",
        "reason_read_failed":  "No se puede leer el tamaño: {err}",
        "reason_start_failed": "Error al iniciar ffmpeg: {err}",
        "reason_early_abort":  "Cancelación anticipada ({pct:.0f}% hecho, {ratio:.1%} > umbral {thr:.0%})",
        "reason_failed":       "Transcodificación fallida (rc={rc}): {err}",
        "reason_no_benefit":   "Sin beneficio ({ratio:.2%} > umbral {thr:.0%}, {orig} -> {new})",
        "reason_recycle_fail": "Error al mover al reciclaje, temporal conservado",
        "reason_rename_fail":  "Error al renombrar temporal: {err}",
        "reason_success":      "{orig} -> {new} (ratio {ratio:.2%}, ahorrado {saved})",
        "log_start":           "=== Inicio src={src} encoder={enc} CQ={cq} threshold={thr} ===",
        "log_scan_done":       "Escaneo: total {total}, omitidos {skipped}, pendientes {pending}",
        "log_no_pending":      "Listo: sin pendientes. escaneados={total} omitidos={skipped}",
        "log_end":             "=== Fin: éxito {s} / omitido {sk} / fallido {f}, ahorrado {saved} ===",
        "recycle_fail":        "Error moviendo al reciclaje: {src} -> {dst}: {err}",
        "conflict_backup":     "Destino existe, respaldado en: {path}",
        "progress_err":        "Excepción leyendo progreso: {err}",
        "unexpected":          "Excepción inesperada: {err}",
        "log_success":         "[éxito]",
        "log_skipped":         "[omitido]",
        "log_failed":          "[fallido]",
    },
    "ja": {
        "source_not_found":    "ソースディレクトリが見つかりません: {path}",
        "ffmpeg_not_found":    "{name}が見つかりません: {err}",
        "ffmpeg_bad_rc":       "{name}の実行に失敗: returncode={rc}",
        "state_corrupt":       "状態ファイルが破損しています。再作成します",
        "save_state_failed":   "状態ファイルの保存に失敗: {err}",
        "scanning":            "スキャン中 [{count}件]: {dir}",
        "scan_done":           "スキャン完了: {count}個の動画ファイルを検出",
        "cache_hit":           "スキャンキャッシュを使用（{count}ファイル、{time}にキャッシュ）",
        "cache_expired":       "キャッシュが期限切れです。再スキャンします...",
        "cache_saved":         "スキャン結果をキャッシュしました（{count}ファイル）",
        "no_pending":          "処理対象なし（スキャン {total}件、スキップ {skipped}件）",
        "pending_info":        "スキャン {total}件、スキップ {skipped}件、処理対象 {pending}件",
        "interrupted":         "中断されました。進行状況を保存済み。次回実行時に自動再開します。",
        "all_done":            "完了！",
        "success_label":       "成功",
        "skipped_label":       "スキップ",
        "failed_label":        "失敗",
        "total_saved":         "合計節約容量：",
        "see_log":             "ログファイル：{path}",
        "reset_failed_done":   "{count}件の失敗エントリを削除しました。次回実行時に再試行します。",
        "panel_title":         "NAS動画 一括AV1変換",
        "panel_total":         "総ファイル数",
        "panel_done_rem":      "処理済 / 残り",
        "panel_stats":         "成功 / スキップ / 失敗",
        "panel_saved":         "節約容量",
        "panel_elapsed":       "経過時間",
        "panel_eta":           "残り時間",
        "panel_current":       "現在のファイル",
        "panel_progress":      "進行状況",
        "panel_ratio":         "予測圧縮率",
        "panel_threshold":     "閾値",
        "hdr_source":          "ソース",
        "hdr_recycle":         "ごみ箱",
        "hdr_encoder":         "エンコーダー",
        "hdr_log":             "ログ",
        "hdr_lang":            "言語",
        "hdr_cache":           "スキャンキャッシュ",
        "cache_hours_fmt":     "{h}h（--rescan で強制再スキャン）",
        "cache_off":           "無効（常に再スキャン）",
        "reason_mp4_exists":   "対応する.mp4が既に存在します",
        "reason_is_av1":       "ソースが既にAV1です",
        "reason_zero_byte":    "ソースファイルが0バイトです",
        "reason_read_failed":  "ファイルサイズを読み取れません: {err}",
        "reason_start_failed": "ffmpegの起動に失敗: {err}",
        "reason_early_abort":  "早期中止（{pct:.0f}%時点で予測圧縮率 {ratio:.1%} > 閾値 {thr:.0%}）",
        "reason_failed":       "変換失敗 (rc={rc}): {err}",
        "reason_no_benefit":   "効果なし（{ratio:.2%} > 閾値 {thr:.0%}、{orig} -> {new}）",
        "reason_recycle_fail": "ごみ箱への移動に失敗。データ損失防止のため一時ファイルを保持",
        "reason_rename_fail":  "一時ファイルのリネームに失敗: {err}",
        "reason_success":      "{orig} -> {new}（圧縮率 {ratio:.2%}、節約 {saved}）",
        "log_start":           "=== 変換開始 src={src} encoder={enc} CQ={cq} threshold={thr} ===",
        "log_scan_done":       "スキャン完了: 合計 {total}、スキップ {skipped}、処理対象 {pending}",
        "log_no_pending":      "完了：処理対象なし。スキャン={total} スキップ={skipped}",
        "log_end":             "=== 終了: 成功 {s} / スキップ {sk} / 失敗 {f}、節約 {saved} ===",
        "recycle_fail":        "ごみ箱への移動に失敗: {src} -> {dst}: {err}",
        "conflict_backup":     "対象が存在します。バックアップ: {path}",
        "progress_err":        "進行状況の読み取り中に例外: {err}",
        "unexpected":          "予期せぬ例外: {err}",
        "log_success":         "[成功]",
        "log_skipped":         "[スキップ]",
        "log_failed":          "[失敗]",
    },
}


def T(key: str, **kwargs) -> str:
    lang = CONFIG.get("LANGUAGE", "zh")
    strings = _STRINGS.get(lang, _STRINGS["zh"])
    s = strings.get(key, _STRINGS["zh"].get(key, key))
    return s.format(**kwargs) if kwargs else s


console = Console()


# ---------- 共用工具 ----------

def setup_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("transcode_av1")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    return logger


def normalize_path(p: Path) -> str:
    """一致的狀態檔鍵值（大小寫不分）"""
    return str(p).lower()


def load_state(state_path: Path) -> Dict:
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 正規化 key（Windows 路徑不分大小寫），避免大小寫不一致導致重複處理
            raw = data.get("processed", {})
            data["processed"] = {k.lower(): v for k, v in raw.items()}
            return data
        except (json.JSONDecodeError, OSError):
            console.print(f"[yellow]{T('state_corrupt')}[/yellow]")
    return {"processed": {}}


def save_state(state_path: Path, state: Dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp.replace(state_path)
    except OSError as e:
        console.print(f"[red]{T('save_state_failed', err=e)}[/red]")


def format_size(size_bytes: float) -> str:
    sign = "-" if size_bytes < 0 else ""
    size = abs(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{sign}{size:,.2f} {unit}"
        size /= 1024.0
    return f"{sign}{size:,.2f} PB"


def format_duration(seconds: float) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:
        return "--:--:--"
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def check_ffmpeg(config: Dict) -> bool:
    for tool_key, name in (("FFMPEG_PATH", "ffmpeg"), ("FFPROBE_PATH", "ffprobe")):
        try:
            r = subprocess.run(
                [config[tool_key], "-version"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                console.print(f"[red]{T('ffmpeg_bad_rc', name=name, rc=r.returncode)}[/red]")
                return False
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            console.print(f"[red]{T('ffmpeg_not_found', name=name, err=e)}[/red]")
            return False
    return True


# ---------- 掃描與快取 ----------

def _try_load_scan_cache(state: Dict, source_dir: Path, cache_hours: float) -> Optional[List[Path]]:
    cache = state.get("scan_cache", {})
    if not cache or cache_hours <= 0:
        return None
    if cache.get("source_dir", "").lower() != str(source_dir).lower():
        return None
    try:
        cached_at = datetime.fromisoformat(cache["scanned_at"])
        age_h = (datetime.now() - cached_at).total_seconds() / 3600
        if age_h > cache_hours:
            console.print(f"[yellow]{T('cache_expired')}[/yellow]")
            return None
        files = [Path(p) for p in cache["files"]]
        console.print(
            f"[cyan]{T('cache_hit', count=len(files), time=cached_at.strftime('%m-%d %H:%M'))}[/cyan]"
        )
        return files
    except (KeyError, ValueError):
        return None


def _save_scan_cache(state: Dict, source_dir: Path, files: List[Path]) -> None:
    state["scan_cache"] = {
        "source_dir": str(source_dir),
        "scanned_at": datetime.now().isoformat(),
        "files": [str(f) for f in files],
    }


def scan_videos(
    source_dir: Path,
    extensions: List[str],
    state: Dict,
    cache_hours: float,
    force_rescan: bool,
) -> List[Path]:
    """掃描影片檔案。掃描過程顯示即時進度；支援快取。"""
    if not force_rescan:
        cached = _try_load_scan_cache(state, source_dir, cache_hours)
        if cached is not None:
            return cached

    exts_lower = {ext.lower() for ext in extensions}
    videos: List[Path] = []

    with console.status("", spinner="dots") as status:
        for root, _, files in os.walk(source_dir):
            dir_name = Path(root).name or root
            status.update(
                f"[cyan]{T('scanning', count=len(videos), dir=dir_name)}[/cyan]"
            )
            for fn in files:
                if Path(fn).suffix.lower() in exts_lower:
                    videos.append(Path(root) / fn)

    videos.sort()
    console.print(f"[green]{T('scan_done', count=len(videos))}[/green]")

    if cache_hours > 0:
        _save_scan_cache(state, source_dir, videos)
        console.print(f"[dim]{T('cache_saved', count=len(videos))}[/dim]")

    return videos


def build_pending_videos(
    all_videos: List[Path],
    processed_map: Dict[str, Dict],
) -> Tuple[List[Path], int]:
    """依狀態檔與實際檔案狀態建立待處理清單。"""
    pending: List[Path] = []
    skipped_existing = 0

    for v in all_videos:
        key = normalize_path(v)
        rec = processed_map.get(key)

        if rec:
            status = rec.get("status", "")
            if status == "success":
                skipped_existing += 1
                continue
            if status == "skipped":
                # 快速信任：.mp4 已存在、來源是 AV1 -> 不重複驗證
                reason = rec.get("reason", "")
                if any(kw in reason for kw in ("mp4", "AV1", "av1", "存在", "exists", "already", "既に", "ya")):
                    skipped_existing += 1
                    continue

        # 實際確認 .mp4 是否存在
        if v.suffix.lower() != ".mp4" and v.with_suffix(".mp4").exists():
            skipped_existing += 1
            processed_map[key] = {
                "status": "skipped",
                "reason": T("reason_mp4_exists"),
                "bytes_saved": 0,
                "time": datetime.now().isoformat(),
            }
            continue

        pending.append(v)

    return pending, skipped_existing


def sort_pending_videos(videos: List[Path], sort_mode: str) -> List[Path]:
    """可插拔排序策略：
    - path_asc: 路徑字典序（舊行為）
    - size_desc: 檔案大的優先
    - recent_upload: 最近上傳/修改優先（mtime 新到舊）
    """
    def _safe_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _safe_mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    if sort_mode == "size_desc":
        return sorted(
            videos,
            key=lambda p: (
                -_safe_size(p),
                str(p).lower(),
            ),
        )
    if sort_mode == "recent_upload":
        return sorted(
            videos,
            key=lambda p: (
                -_safe_mtime(p),
                str(p).lower(),
            ),
        )
    return sorted(videos, key=lambda p: str(p).lower())


def resolve_sort_mode(sort_arg: str) -> str:
    mapping = {
        "0": "path_asc",
        "default": "path_asc",
        "path_asc": "path_asc",
        "1": "size_desc",
        "size_desc": "size_desc",
        "2": "recent_upload",
        "recent_upload": "recent_upload",
    }
    return mapping.get(sort_arg, "path_asc")


# ---------- 影片資訊 ----------

def get_video_info(video_path: Path, ffprobe: str) -> Dict:
    info: Dict = {"duration": None, "codec": None, "audio_codec": None}
    try:
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "stream=codec_name,codec_type",
            "-show_entries", "format=duration",
            "-of", "json",
            str(video_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            fmt = data.get("format", {})
            try:
                info["duration"] = float(fmt["duration"])
            except (KeyError, ValueError, TypeError):
                pass
            for s in data.get("streams", []):
                codec = s.get("codec_name", "").lower()
                ctype = s.get("codec_type", "").lower()
                if ctype == "video" and info["codec"] is None:
                    info["codec"] = codec
                elif ctype == "audio" and info["audio_codec"] is None:
                    info["audio_codec"] = codec
    except Exception:
        pass
    return info


# ---------- FFmpeg 命令建立 ----------

def build_ffmpeg_cmd(
    input_path: Path, output_path: Path, config: Dict, audio_codec: Optional[str] = None
) -> List[str]:
    cmd: List[str] = [
        config["FFMPEG_PATH"],
        "-hide_banner", "-loglevel", "error", "-nostats",
        "-y", "-i", str(input_path),
    ]

    encoder = config["ENCODER"].lower()
    bit_depth = config.get("BIT_DEPTH", 8)
    pix_fmt = "yuv420p10le" if bit_depth == 10 else "yuv420p"

    if encoder == "av1_nvenc":
        cmd += [
            # format={pix_fmt} forces bit-depth conversion before the encoder;
            # without it, DJI 10-bit HEVC passes yuv420p10le to av1_nvenc which
            # then writes an invalid AV1 sequence header and fails to mux into MP4.
            "-vf", f"scale=trunc(iw/8)*8:trunc(ih/8)*8,format={pix_fmt}",
            "-c:v", "av1_nvenc",
            "-preset", str(config["NVENC_PRESET"]),
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", str(config["CQ_VALUE"]),
            "-b:v", "0",
            "-pix_fmt", pix_fmt,
        ]
    elif encoder == "libsvtav1":
        cmd += [
            "-vf", f"scale=trunc(iw/8)*8:trunc(ih/8)*8,format={pix_fmt}",
            "-c:v", "libsvtav1",
            "-preset", str(config["SVTAV1_PRESET"]),
            "-crf", str(config["CQ_VALUE"]),
            "-pix_fmt", pix_fmt,
        ]
    else:
        raise ValueError(f"Unsupported encoder: {encoder}")

    # :0 = primary stream only — avoids DJI secondary thumbnail/preview video tracks
    cmd += ["-map", "0:v:0"]
    cmd += ["-map_metadata", "-1"]

    _MP4_COMPAT_AUDIO = {"aac", "mp3", "opus", "ac3", "eac3", "mp2", "flac"}
    if audio_codec is None:
        cmd += ["-an"]
    else:
        cmd += ["-map", "0:a?"]
        if audio_codec in _MP4_COMPAT_AUDIO:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "128k"]

    sub_mode = config.get("SUBTITLE_MODE", "copy").lower()
    if sub_mode == "ignore":
        cmd += ["-sn", "-dn"]
    else:
        cmd += ["-dn"]
        cmd += ["-map", "0:s?"]
        cmd += ["-c:s", "mov_text" if sub_mode == "mov_text" else "copy"]

    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostdin", str(output_path)]
    return cmd


# ---------- 進度解析 ----------

def parse_progress_line(line: str, state: Dict) -> None:
    if "=" not in line:
        return
    key, _, value = line.partition("=")
    key, value = key.strip(), value.strip()

    if key in ("out_time_ms", "out_time_us"):
        try:
            state["out_time_sec"] = int(value) / 1_000_000
        except ValueError:
            pass
    elif key == "fps":
        try:
            state["fps"] = float(value)
        except ValueError:
            pass
    elif key == "speed":
        m = re.match(r"([0-9.]+)x", value)
        if m:
            try:
                state["speed"] = float(m.group(1))
            except ValueError:
                pass
    elif key == "frame":
        try:
            state["frame"] = int(value)
        except ValueError:
            pass
    elif key == "progress":
        state["progress"] = value


# ---------- Live 面板 ----------

def make_panel(snap: Dict) -> Panel:
    total = snap.get("total", 0)
    done = snap.get("done", 0)
    success = snap.get("success", 0)
    skipped = snap.get("skipped", 0)
    failed = snap.get("failed", 0)
    remaining = total - done
    elapsed = snap.get("elapsed", 0.0)
    eta = snap.get("eta", 0.0)
    current_file = snap.get("current_file", "-")
    pct = snap.get("cur_progress", 0.0)
    fps = snap.get("cur_fps", 0.0)
    speed = snap.get("cur_speed", 0.0)
    saved = snap.get("saved_bytes", 0)
    projected_ratio = snap.get("cur_projected_ratio", 0.0)
    size_threshold = snap.get("size_threshold", 0.8)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", justify="right", no_wrap=True)
    table.add_column()

    table.add_row(T("panel_total"), f"{total}")
    table.add_row(T("panel_done_rem"), f"{done} / {remaining}")
    table.add_row(
        T("panel_stats"),
        f"[green]{success}[/green] / [yellow]{skipped}[/yellow] / [red]{failed}[/red]",
    )
    table.add_row(T("panel_saved"), f"[green]{format_size(saved)}[/green]")
    table.add_row(T("panel_elapsed"), format_duration(elapsed))
    table.add_row(T("panel_eta"), format_duration(eta))
    table.add_row("", "")
    table.add_row(T("panel_current"), f"[white]{current_file}[/white]")

    bar_w = 40
    pct_c = max(0.0, min(pct, 100.0))
    filled = int(bar_w * pct_c / 100)
    bar = "█" * filled + "░" * (bar_w - filled)
    table.add_row(
        T("panel_progress"),
        f"[{bar}] {pct_c:5.1f}%   fps={fps:.1f}   speed={speed:.2f}x",
    )

    if projected_ratio > 0:
        ratio_color = "red" if projected_ratio > size_threshold else "green"
        table.add_row(
            T("panel_ratio"),
            f"[{ratio_color}]{projected_ratio:.1%}[/{ratio_color}]"
            f"  （{T('panel_threshold')} {size_threshold:.0%}）",
        )

    return Panel(table, title=f"[bold]{T('panel_title')}[/bold]", border_style="cyan")


# ---------- 軟刪除 ----------

def safe_move_to_recycle(
    src: Path, source_root: Path, recycle_root: Path, logger: logging.Logger,
) -> Optional[Path]:
    try:
        rel = src.relative_to(source_root)
    except ValueError:
        rel = Path(src.name)
    target = recycle_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = target.with_name(f"{target.stem}_{ts}{target.suffix}")

    try:
        shutil.move(str(src), str(target))
        return target
    except OSError as e:
        logger.error(T("recycle_fail", src=src, dst=target, err=e))
        return None


# ---------- 單檔轉檔 ----------

def process_one(
    video: Path,
    config: Dict,
    source_root: Path,
    recycle_root: Path,
    logger: logging.Logger,
    progress_cb: Callable[[float, float, float, float], None],
) -> Tuple[str, str, int]:
    final_output = video.with_suffix(".mp4")
    tmp_output = video.with_name(f"{video.stem}_tmp.mp4")

    if video.suffix.lower() != ".mp4" and final_output.exists():
        return ("skipped", T("reason_mp4_exists"), 0)

    try:
        original_size = video.stat().st_size
    except OSError as e:
        return ("failed", T("reason_read_failed", err=e), 0)
    if original_size == 0:
        return ("failed", T("reason_zero_byte"), 0)

    video_info = get_video_info(video, config["FFPROBE_PATH"])
    duration = video_info["duration"] or 0.0

    if video_info["codec"] == "av1":
        return ("skipped", T("reason_is_av1"), 0)

    if tmp_output.exists():
        try:
            tmp_output.unlink()
        except OSError:
            pass

    cmd = build_ffmpeg_cmd(video, tmp_output, config, video_info.get("audio_codec"))

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except OSError as e:
        return ("failed", T("reason_start_failed", err=e), 0)

    prog: Dict = {
        "out_time_sec": 0.0, "fps": 0.0, "speed": 0.0,
        "frame": 0, "progress": "continue",
    }
    early_abort_start = config.get("EARLY_ABORT_START_PCT", 20)
    last_size_check_time = 0.0
    early_aborted = False
    abort_pct = 0.0
    projected_ratio = 0.0

    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            parse_progress_line(line, prog)
            if duration > 0:
                pct = max(0.0, min((prog["out_time_sec"] / duration) * 100.0, 99.9))
            else:
                pct = 0.0

            now = time.time()
            if pct >= early_abort_start and now - last_size_check_time >= 5.0:
                last_size_check_time = now
                try:
                    if tmp_output.exists():
                        tmp_sz = tmp_output.stat().st_size
                        if tmp_sz >= 1024 * 1024 and pct > 0:
                            projected = tmp_sz / (pct / 100.0)
                            projected_ratio = projected / original_size
                            if projected_ratio > config["SIZE_THRESHOLD"]:
                                proc.kill()
                                abort_pct = pct
                                early_aborted = True
                                break
                except OSError:
                    pass

            progress_cb(pct, prog.get("fps", 0.0), prog.get("speed", 0.0), projected_ratio)
            if prog["progress"] == "end":
                break
    except Exception as e:
        logger.error(T("progress_err", err=e))

    try:
        _, stderr_data = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, stderr_data = proc.communicate()
    retcode = proc.returncode

    if early_aborted:
        if tmp_output.exists():
            try:
                tmp_output.unlink()
            except OSError:
                pass
        return (
            "skipped",
            T("reason_early_abort", pct=abort_pct, ratio=projected_ratio, thr=config["SIZE_THRESHOLD"]),
            0,
        )

    if retcode != 0 or not tmp_output.exists() or tmp_output.stat().st_size == 0:
        if tmp_output.exists():
            try:
                tmp_output.unlink()
            except OSError:
                pass
        err_tail = (stderr_data or "")[-1000:].strip().replace("\n", " | ")
        return ("failed", T("reason_failed", rc=retcode, err=err_tail), 0)

    new_size = tmp_output.stat().st_size
    ratio = new_size / original_size

    if ratio > config["SIZE_THRESHOLD"]:
        try:
            tmp_output.unlink()
        except OSError:
            pass
        return (
            "skipped",
            T("reason_no_benefit",
              ratio=ratio, thr=config["SIZE_THRESHOLD"],
              orig=format_size(original_size), new=format_size(new_size)),
            0,
        )

    recycled = safe_move_to_recycle(video, source_root, recycle_root, logger)
    if recycled is None:
        return ("failed", T("reason_recycle_fail"), 0)

    try:
        if final_output.exists():
            backup = final_output.with_name(
                f"{final_output.stem}_conflict_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            )
            logger.warning(T("conflict_backup", path=backup))
            final_output.rename(backup)
        tmp_output.rename(final_output)
    except OSError as e:
        logger.error(T("reason_rename_fail", err=e))
        return ("failed", T("reason_rename_fail", err=e), 0)

    saved = original_size - new_size
    return (
        "success",
        T("reason_success",
          orig=format_size(original_size), new=format_size(new_size),
          ratio=ratio, saved=format_size(saved)),
        saved,
    )


# ---------- 主流程 ----------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NAS Video Batch AV1 Transcoder / NAS 影片批次 AV1 轉檔工具"
    )
    p.add_argument(
        "--lang", choices=["zh", "en", "es", "ja"],
        help="Override display language / 覆蓋顯示語言",
    )
    p.add_argument(
        "--rescan", action="store_true",
        help="Force fresh file scan, ignore cache / 強制重新掃描，忽略快取",
    )
    p.add_argument(
        "--reset-failed", action="store_true",
        help="Remove failed entries from state so they are retried / 清除失敗記錄，讓下次執行重試",
    )
    p.add_argument(
        "--sort", default="0",
        help=(
            "Transcode order: 0=path_asc(default), 1=size_desc, 2=recent_upload "
            "/ 轉檔順序：0=路徑順序(預設)、1=大檔優先、2=最近上傳優先"
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.lang:
        CONFIG["LANGUAGE"] = args.lang

    sort_mode = resolve_sort_mode(args.sort)

    source_root = Path(CONFIG["SOURCE_DIR"])
    recycle_root = Path(CONFIG["RECYCLE_DIR"])
    log_path = Path(CONFIG["LOG_FILE"]).resolve()
    state_path = Path(CONFIG["STATE_FILE"]).resolve()

    if not source_root.is_dir():
        console.print(f"[bold red]{T('source_not_found', path=source_root)}[/bold red]")
        sys.exit(1)
    recycle_root.mkdir(parents=True, exist_ok=True)

    if not check_ffmpeg(CONFIG):
        sys.exit(1)

    logger = setup_logger(log_path)
    state = load_state(state_path)
    processed_map: Dict[str, Dict] = state.get("processed", {})

    # --reset-failed：清除失敗記錄，讓下次執行重試
    if args.reset_failed:
        failed_keys = [k for k, v in processed_map.items() if v.get("status") == "failed"]
        for k in failed_keys:
            del processed_map[k]
        state["processed"] = processed_map
        save_state(state_path, state)
        console.print(f"[green]{T('reset_failed_done', count=len(failed_keys))}[/green]")
        return

    cache_h = CONFIG.get("SCAN_CACHE_HOURS", 0)
    cache_info = (
        T("cache_hours_fmt", h=cache_h) if cache_h > 0 else T("cache_off")
    )
    preset_val = (
        CONFIG["NVENC_PRESET"] if CONFIG["ENCODER"] == "av1_nvenc" else CONFIG["SVTAV1_PRESET"]
    )

    console.print(f"[bold cyan]{T('hdr_source')}   :[/bold cyan] {source_root}")
    console.print(f"[bold cyan]{T('hdr_recycle')}   :[/bold cyan] {recycle_root}")
    console.print(
        f"[bold cyan]{T('hdr_encoder')}   :[/bold cyan] {CONFIG['ENCODER']}"
        f"  CQ={CONFIG['CQ_VALUE']}  preset={preset_val}"
    )
    console.print(f"[bold cyan]{T('hdr_log')}   :[/bold cyan] {log_path}")
    console.print(f"[bold cyan]{T('hdr_lang')}   :[/bold cyan] {CONFIG['LANGUAGE']}")
    console.print(f"[bold cyan]{T('hdr_cache')}   :[/bold cyan] {cache_info}")
    console.print(f"[bold cyan]Sort order   :[/bold cyan] {sort_mode}")

    logger.info(T("log_start",
                  src=source_root, enc=CONFIG["ENCODER"],
                  cq=CONFIG["CQ_VALUE"], thr=CONFIG["SIZE_THRESHOLD"]))

    all_videos = scan_videos(
        source_root, CONFIG["VIDEO_EXTENSIONS"], state, cache_h, args.rescan
    )

    pending, skipped_existing = build_pending_videos(all_videos, processed_map)
    pending = sort_pending_videos(pending, sort_mode)

    save_state(state_path, {"processed": processed_map, "scan_cache": state.get("scan_cache", {})})

    total = len(pending)
    if total == 0:
        console.print(f"[green]{T('no_pending', total=len(all_videos), skipped=skipped_existing)}[/green]")
        logger.info(T("log_no_pending", total=len(all_videos), skipped=skipped_existing))
        return

    console.print(f"[green]{T('pending_info', total=len(all_videos), skipped=skipped_existing, pending=total)}[/green]")
    logger.info(T("log_scan_done", total=len(all_videos), skipped=skipped_existing, pending=total))

    counters: Dict = {
        "total": total, "done": 0,
        "success": 0, "skipped": 0, "failed": 0,
        "elapsed": 0.0, "eta": 0.0,
        "current_file": "-",
        "cur_progress": 0.0, "cur_fps": 0.0, "cur_speed": 0.0,
        "cur_projected_ratio": 0.0,
        "size_threshold": CONFIG["SIZE_THRESHOLD"],
        "saved_bytes": 0,
    }
    start_time = time.time()

    with Live(make_panel(counters), console=console, refresh_per_second=4) as live:

        def update_progress(pct: float, fps: float, speed: float, projected_ratio: float = 0.0) -> None:
            counters["cur_progress"] = pct
            counters["cur_fps"] = fps
            counters["cur_speed"] = speed
            counters["cur_projected_ratio"] = projected_ratio
            counters["elapsed"] = time.time() - start_time
            if counters["done"] > 0:
                avg = counters["elapsed"] / counters["done"]
                counters["eta"] = avg * (counters["total"] - counters["done"])
            live.update(make_panel(counters))

        for idx, video in enumerate(pending, 1):
            counters["current_file"] = f"[{idx}/{total}] {video}"
            counters["cur_progress"] = 0.0
            counters["cur_fps"] = 0.0
            counters["cur_speed"] = 0.0
            counters["cur_projected_ratio"] = 0.0
            counters["elapsed"] = time.time() - start_time
            live.update(make_panel(counters))

            try:
                status, reason, saved = process_one(
                    video, CONFIG, source_root, recycle_root, logger, update_progress,
                )
            except Exception as e:
                status, reason, saved = "failed", T("unexpected", err=e), 0

            counters["done"] += 1
            if status == "success":
                counters["success"] += 1
                counters["saved_bytes"] += saved
                logger.info(f"{T('log_success')} {video} | {reason}")
                console.print(f"  [green]✓[/green] {video}")
            elif status == "skipped":
                counters["skipped"] += 1
                logger.info(f"{T('log_skipped')} {video} | {reason}")
                console.print(f"  [dim]→[/dim] {video}")
            else:
                counters["failed"] += 1
                logger.error(f"{T('log_failed')} {video} | {reason}")
                console.print(f"  [red]✗[/red] {video}")

            key = normalize_path(video)
            processed_map[key] = {
                "status": status,
                "reason": reason,
                "bytes_saved": saved,
                "time": datetime.now().isoformat(),
            }
            save_state(
                state_path,
                {"processed": processed_map, "scan_cache": state.get("scan_cache", {})},
            )

            counters["elapsed"] = time.time() - start_time
            if counters["done"] > 0:
                avg = counters["elapsed"] / counters["done"]
                counters["eta"] = avg * (counters["total"] - counters["done"])
            live.update(make_panel(counters))

    logger.info(T("log_end",
                  s=counters["success"], sk=counters["skipped"], f=counters["failed"],
                  saved=format_size(counters["saved_bytes"])))
    console.print(
        f"\n[bold green]{T('all_done')}[/bold green]  "
        f"{T('success_label')} [green]{counters['success']}[/green] / "
        f"{T('skipped_label')} [yellow]{counters['skipped']}[/yellow] / "
        f"{T('failed_label')} [red]{counters['failed']}[/red]"
    )
    console.print(f"[bold]{T('total_saved')}[/bold] [green]{format_size(counters['saved_bytes'])}[/green]")
    console.print(T("see_log", path=log_path))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print(f"\n[yellow]{T('interrupted')}[/yellow]")
        sys.exit(130)
