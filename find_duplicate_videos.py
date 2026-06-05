#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
影片重複檔案偵測與清理工具
==============================
掃描來源目錄，找出同一資料夾內檔名相同但副檔名不同的影片，
用 ffprobe 比對畫質（解析度、codec、bitrate），
列出建議後詢問是否批次刪除較差的版本。

執行需求
- Python 3.9+、pip install rich
- 系統 PATH 需有 ffprobe (建議 7.x+)

用法
  python find_duplicate_videos.py [--source <路徑>] [--dry-run] [--lang zh|en]
"""

import os
import re
import sys
import json
import shutil
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.prompt import Prompt, Confirm
    from rich.progress import (
        Progress, SpinnerColumn, TextColumn,
        BarColumn, TaskProgressColumn, TimeElapsedColumn,
    )
except ImportError:
    print("Error: pip install rich")
    sys.exit(1)


# ============================================================
# 使用者設定區
# ============================================================
CONFIG = {
    "SOURCE_DIR":   r"\\192.168.3.8\james",
    "RECYCLE_DIR":  r"\\192.168.3.8\james\#recycle",   # 設為 "" 則直接刪除
    "LOG_FILE":     str(Path(__file__).resolve().parent / "duplicate_cleanup.log"),
    "FFPROBE_PATH": "ffprobe",
    "VIDEO_EXTENSIONS": [".mov", ".mpg", ".mpeg", ".avi", ".mp4", ".mkv", ".wmv", ".flv", ".ts", ".m2ts"],
    "LANGUAGE": "zh",
    # 時長差異容許範圍（秒）：超過此值則視為不同影片，標示警告
    "DURATION_TOLERANCE_SEC": 5.0,
}
# ============================================================


# ============================================================
# 多語系字串
# ============================================================
_S: Dict[str, Dict[str, str]] = {
    "zh": {
        "title":             "影片重複檔案偵測工具",
        "source_label":      "來源目錄",
        "ffprobe_missing":   "找不到 ffprobe，請確認已安裝並在 PATH 中",
        "source_missing":    "來源目錄不存在: {path}",
        "scanning":          "正在掃描...",
        "scan_done":         "掃描完成：找到 {groups} 組重複檔案（共 {files} 個檔案）",
        "no_duplicates":     "未發現重複檔案，所有影片檔名均唯一。",
        "group_header":      "群組 {n}/{total}：{stem}",
        "col_file":          "檔案",
        "col_size":          "大小",
        "col_res":           "解析度",
        "col_codec":         "Codec",
        "col_bitrate":       "Bitrate",
        "col_duration":      "時長",
        "col_score":         "品質分",
        "col_action":        "建議",
        "action_keep":       "保留",
        "action_delete":     "刪除",
        "action_manual":     "手動決定",
        "warn_duration":     "警告：時長差異 {diff:.1f} 秒，可能不是同一影片！",
        "warn_compat":       "注意：偵測到 AV1 10-bit，因播放器相容性問題，建議保留原始錄影格式",
        "warn_mjpeg":        "注意：偵測到 MJPEG 原始錄影格式與 H264 並存，當年 H264 轉檔品質不確定，建議保留 MJPEG",
        "warn_no_info":      "無法取得影片資訊",
        "prompt_main":       "\n如何處理？ [A=全部刪除建議項, S=逐組選擇, N=取消]",
        "prompt_group":      "群組 {n}：刪除 {file}？[y/N]",
        "dry_run_label":     "[DRY-RUN] 將會刪除",
        "deleted_recycle":   "已移至回收：{path}",
        "deleted_direct":    "已刪除：{path}",
        "delete_failed":     "刪除失敗：{path} — {err}",
        "summary":           "完成：刪除 {deleted} 個檔案，釋放 {saved}",
        "cancelled":         "已取消，未刪除任何檔案。",
        "log_start":         "=== 開始掃描 source={src} ===",
        "log_end":           "=== 結束：刪除 {deleted} 個，釋放 {saved} ===",
        "score_explain":     "品質分 = 解析度像素 × codec效率；分數越高畫質越好",
    },
    "en": {
        "title":             "Duplicate Video Detector",
        "source_label":      "Source directory",
        "ffprobe_missing":   "ffprobe not found — please install it and ensure it is in PATH",
        "source_missing":    "Source directory does not exist: {path}",
        "scanning":          "Scanning...",
        "scan_done":         "Scan complete: {groups} duplicate group(s) found ({files} files total)",
        "no_duplicates":     "No duplicates found — all video filenames are unique.",
        "group_header":      "Group {n}/{total}: {stem}",
        "col_file":          "File",
        "col_size":          "Size",
        "col_res":           "Resolution",
        "col_codec":         "Codec",
        "col_bitrate":       "Bitrate",
        "col_duration":      "Duration",
        "col_score":         "Quality",
        "col_action":        "Action",
        "action_keep":       "KEEP",
        "action_delete":     "DELETE",
        "action_manual":     "Manual",
        "warn_duration":     "Warning: duration differs by {diff:.1f}s — may not be the same video!",
        "warn_compat":       "Note: AV1 10-bit detected — recommending original format due to playback compatibility",
        "warn_mjpeg":        "Note: MJPEG (original recording) detected alongside H264 — keeping MJPEG as early H264 transcoding quality is uncertain",
        "warn_no_info":      "Could not read video info",
        "prompt_main":       "\nHow to proceed? [A=delete all recommended, S=select per group, N=cancel]",
        "prompt_group":      "Group {n}: delete {file}? [y/N]",
        "dry_run_label":     "[DRY-RUN] Would delete",
        "deleted_recycle":   "Recycled: {path}",
        "deleted_direct":    "Deleted: {path}",
        "delete_failed":     "Delete failed: {path} — {err}",
        "summary":           "Done: {deleted} file(s) deleted, {saved} freed",
        "cancelled":         "Cancelled — nothing was deleted.",
        "log_start":         "=== Scan started source={src} ===",
        "log_end":           "=== Done: deleted {deleted}, freed {saved} ===",
        "score_explain":     "Quality = pixels × codec efficiency; higher = better",
    },
}


# ============================================================
# Codec 效率排名（越高 = 越現代/高效，相同解析度下畫質通常更好）
# ============================================================
CODEC_RANK: Dict[str, int] = {
    "av1":         10,
    "hevc":        9,
    "h265":        9,
    "vp9":         8,
    "h264":        7,
    "avc":         7,
    "mpeg4":       5,
    "xvid":        5,
    "divx":        5,
    "wmv3":        4,
    "vc1":         4,
    "theora":      3,
    "mpeg2video":  3,
    "mpeg1video":  2,
}

console = Console()


def t(key: str, lang: str, **kwargs) -> str:
    s = _S.get(lang, _S["zh"]).get(key, key)
    return s.format(**kwargs) if kwargs else s


def setup_logging(log_path: str) -> logging.Logger:
    logger = logging.getLogger("dup_video")
    logger.setLevel(logging.INFO)
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)
    except Exception as e:
        console.print(f"[yellow]Warning: cannot open log file {log_path}: {e}[/yellow]")
    return logger


def check_ffprobe(ffprobe_path: str, lang: str) -> bool:
    try:
        r = subprocess.run([ffprobe_path, "-version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        console.print(f"[red]{t('ffprobe_missing', lang)}[/red]")
        return False


def fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_duration(secs: Optional[float]) -> str:
    if secs is None:
        return "—"
    s = int(secs)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_bitrate(bps: Optional[int]) -> str:
    if bps is None or bps <= 0:
        return "—"
    if bps >= 1_000_000:
        return f"{bps/1_000_000:.1f} Mbps"
    return f"{bps/1_000:.0f} Kbps"


def get_video_info(path: Path, ffprobe: str) -> Dict[str, Any]:
    """用 ffprobe 取得解析度、codec、bit_depth、bitrate、時長。"""
    info: Dict[str, Any] = {
        "width": None, "height": None,
        "codec": None, "bit_depth": None,
        "duration": None, "bitrate": None,
    }
    try:
        cmd = [
            ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name,bit_rate,pix_fmt,bits_per_raw_sample",
            "-show_entries", "format=duration,bit_rate,size",
            "-of", "json",
            str(path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not r.stdout.strip():
            return info
        data = json.loads(r.stdout)
        fmt = data.get("format", {})

        try:
            info["duration"] = float(fmt["duration"])
        except (KeyError, ValueError, TypeError):
            pass

        # bitrate：優先用 format 層級，再用 stream 層級，最後由 size/duration 估算
        try:
            info["bitrate"] = int(fmt["bit_rate"])
        except (KeyError, ValueError, TypeError):
            pass

        streams = data.get("streams", [])
        if streams:
            vs = streams[0]
            for key in ("width", "height"):
                try:
                    info[key] = int(vs[key])
                except (KeyError, ValueError, TypeError):
                    pass
            info["codec"] = vs.get("codec_name", "").lower() or None
            if info["bitrate"] is None:
                try:
                    info["bitrate"] = int(vs["bit_rate"])
                except (KeyError, ValueError, TypeError):
                    pass

            # bit depth：優先用 bits_per_raw_sample，再從 pix_fmt 名稱推斷
            try:
                bprs = int(vs["bits_per_raw_sample"])
                if bprs > 0:
                    info["bit_depth"] = bprs
            except (KeyError, ValueError, TypeError):
                pass
            if info["bit_depth"] is None:
                pix_fmt = vs.get("pix_fmt", "") or ""
                # pix_fmt 如 yuv420p10le / yuv444p12le 等，數字即 bit depth
                m = re.search(r"(\d+)(?:le|be)$", pix_fmt)
                if m:
                    info["bit_depth"] = int(m.group(1))
                elif pix_fmt and not any(c.isdigit() for c in pix_fmt):
                    info["bit_depth"] = 8  # yuv420p 等無數字的為 8-bit

        # 由 size / duration 反推 bitrate
        if info["bitrate"] is None and info["duration"] and info["duration"] > 0:
            try:
                file_size = int(fmt["size"])
                info["bitrate"] = int(file_size * 8 / info["duration"])
            except (KeyError, ValueError, TypeError):
                pass

    except Exception:
        pass
    return info


def is_10bit_av1(info: Dict) -> bool:
    return info.get("codec") == "av1" and (info.get("bit_depth") or 8) >= 10


def codec_rank(codec: Optional[str]) -> int:
    if not codec:
        return 0
    return CODEC_RANK.get(codec.lower(), 1)


def quality_score(info: Dict) -> float:
    """
    品質分 = 解析度像素 × codec效率系數
    用於判斷哪個檔案畫質較好，不受檔案大小影響。
    """
    w = info.get("width") or 0
    h = info.get("height") or 0
    pixels = w * h
    if pixels == 0:
        return 0.0
    rank = codec_rank(info.get("codec"))
    # codec 效率最高是 10，最低是 1，正規化到 1.0~2.0 倍乘數
    codec_multiplier = 1.0 + rank / 10.0
    return pixels * codec_multiplier


# ============================================================
# 掃描
# ============================================================

def scan_duplicates(
    source: Path,
    extensions: List[str],
    on_progress: Optional[Any] = None,  # callable(dir_str, video_count)
) -> List[List[Path]]:
    """
    遞迴掃描 source，回傳每組「同目錄 + 同檔名不同副檔名」的 Path list。
    每個 list 長度 >= 2。on_progress 每處理完一個目錄就回呼一次。
    """
    ext_set = {e.lower() for e in extensions}
    groups: Dict[str, Dict[str, List[Path]]] = defaultdict(lambda: defaultdict(list))
    video_count = 0

    for root, dirs, files in os.walk(source):
        dirs[:] = [d for d in dirs if not d.startswith(".") and not d.startswith("#")]
        dir_path = str(root)
        for fname in files:
            p = Path(root) / fname
            if p.suffix.lower() in ext_set:
                groups[dir_path][p.stem].append(p)
                video_count += 1
        if on_progress:
            on_progress(dir_path, video_count)

    result = []
    for dir_stems in groups.values():
        for paths in dir_stems.values():
            if len(paths) >= 2:
                result.append(sorted(paths, key=lambda p: p.name.lower()))

    result.sort(key=lambda g: str(g[0]).lower())
    return result


# ============================================================
# 顯示
# ============================================================

def fmt_codec(info: Dict[str, Any]) -> str:
    codec = (info.get("codec") or "—").upper()
    depth = info.get("bit_depth")
    if depth and depth != 8:
        return f"{codec} {depth}bit"
    return codec


def build_group_table(
    group: List[Path],
    infos: List[Dict[str, Any]],
    scores: List[float],
    recommendations: List[str],  # "keep" | "delete" | "manual"
    lang: str,
    override_reason: Optional[str] = None,
) -> Table:
    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column(t("col_file", lang), style="dim", no_wrap=False, ratio=4)
    table.add_column(t("col_size", lang), justify="right", ratio=1)
    table.add_column(t("col_res", lang), justify="center", ratio=1)
    table.add_column(t("col_codec", lang), justify="center", ratio=2)
    table.add_column(t("col_bitrate", lang), justify="right", ratio=1)
    table.add_column(t("col_duration", lang), justify="right", ratio=1)
    table.add_column(t("col_score", lang), justify="right", ratio=1)
    table.add_column(t("col_action", lang), justify="center", ratio=1)

    for path, info, score, rec in zip(group, infos, scores, recommendations):
        size_str = fmt_size(path.stat().st_size) if path.exists() else "?"
        res_str = f"{info['width']}×{info['height']}" if info.get("width") else "—"
        codec_str = fmt_codec(info)
        br_str = fmt_bitrate(info.get("bitrate"))
        dur_str = fmt_duration(info.get("duration"))
        # 相容性覆蓋時不顯示品質分（避免誤導）
        score_str = "—" if override_reason else (f"{score:,.0f}" if score > 0 else "—")

        if rec == "keep":
            action_text = Text(t("action_keep", lang), style="bold green")
            row_style = "green"
        elif rec == "delete":
            action_text = Text(t("action_delete", lang), style="bold red")
            row_style = "red"
        else:
            action_text = Text(t("action_manual", lang), style="bold yellow")
            row_style = "yellow"

        table.add_row(
            Text(path.name, style=row_style),
            Text(size_str, style=row_style),
            Text(res_str, style=row_style),
            Text(codec_str, style=row_style),
            Text(br_str, style=row_style),
            Text(dur_str, style=row_style),
            Text(score_str, style=row_style),
            action_text,
        )

    return table


# ============================================================
# 刪除
# ============================================================

def delete_file(path: Path, recycle_dir: str, dry_run: bool, lang: str, logger: logging.Logger) -> int:
    """刪除一個檔案。回傳釋放的 bytes（dry_run 時也計算）。"""
    try:
        size = path.stat().st_size
    except Exception:
        size = 0

    if dry_run:
        console.print(f"  [yellow]{t('dry_run_label', lang)}:[/yellow] {path}")
        logger.info(f"[DRY-RUN] {path}")
        return size

    try:
        if recycle_dir:
            dst_dir = Path(recycle_dir) / path.parent.relative_to(path.anchor)
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / path.name
            # 避免衝突
            if dst.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dst = dst_dir / f"{path.stem}__{ts}{path.suffix}"
            shutil.move(str(path), str(dst))
            console.print(f"  [green]{t('deleted_recycle', lang, path=path.name)}[/green]")
            logger.info(f"RECYCLED {path} -> {dst}")
        else:
            path.unlink()
            console.print(f"  [green]{t('deleted_direct', lang, path=path.name)}[/green]")
            logger.info(f"DELETED {path}")
        return size
    except Exception as e:
        console.print(f"  [red]{t('delete_failed', lang, path=path, err=e)}[/red]")
        logger.error(f"DELETE_FAILED {path}: {e}")
        return 0


# ============================================================
# 主流程
# ============================================================

def analyze_group(
    group: List[Path],
    ffprobe: str,
    on_file: Optional[Any] = None,  # callable(path) — 每個檔案 ffprobe 完成後回呼
) -> Tuple[List[Dict[str, Any]], List[float], List[str], bool, Optional[str]]:
    """
    回傳 (infos, scores, recommendations, has_duration_warning, override_reason)
    recommendations 元素: "keep" | "delete" | "manual"
    override_reason: None 表示依品質分決定；非 None 表示套用特殊規則
    """
    infos = []
    for p in group:
        infos.append(get_video_info(p, ffprobe))
        if on_file:
            on_file(p)
    scores = [quality_score(info) for info in infos]

    # 時長差異警告
    durations = [info["duration"] for info in infos if info["duration"] is not None]
    has_warning = False
    if len(durations) >= 2:
        diff = max(durations) - min(durations)
        if diff > CONFIG["DURATION_TOLERANCE_SEC"]:
            has_warning = True

    # 特殊規則：群組內有 10-bit AV1 且同時存在非 10-bit AV1 檔案
    # → 不論品質分，一律建議刪除 AV1 10-bit（播放器相容性考量）
    flags_10bit_av1 = [is_10bit_av1(info) for info in infos]
    if any(flags_10bit_av1) and not all(flags_10bit_av1):
        recommendations = ["delete" if f else "keep" for f in flags_10bit_av1]
        return infos, scores, recommendations, has_warning, "compat_10bit_av1"

    # 特殊規則：群組內有 MJPEG 且同時存在 H264
    # → MJPEG 通常是原始錄影格式，H264 為舊時轉檔副本（轉檔品質不確定），建議保留原始
    flags_mjpeg = [info.get("codec") == "mjpeg" for info in infos]
    flags_h264  = [(info.get("codec") or "") in ("h264", "avc") for info in infos]
    if any(flags_mjpeg) and any(flags_h264):
        recommendations = []
        for info in infos:
            c = info.get("codec") or ""
            if c == "mjpeg":
                recommendations.append("keep")
            elif c in ("h264", "avc"):
                recommendations.append("delete")
            else:
                recommendations.append("manual")
        return infos, scores, recommendations, has_warning, "original_mjpeg"

    # 品質分決定推薦
    if all(s == 0 for s in scores):
        # 無法取得任何資訊，只能依檔案大小
        file_sizes = [p.stat().st_size if p.exists() else 0 for p in group]
        max_size = max(file_sizes)
        recommendations = ["keep" if sz == max_size else "delete" for sz in file_sizes]
        if all(r == "keep" for r in recommendations):
            recommendations = ["keep"] + ["delete"] * (len(group) - 1)
    else:
        max_score = max(scores)
        top_count = sum(1 for s in scores if s == max_score)
        if top_count == 1:
            recommendations = ["keep" if s == max_score else "delete" for s in scores]
        else:
            # 同分：用 bitrate 作為 tiebreaker
            max_br = max((info.get("bitrate") or 0) for info in infos)
            recommendations = []
            kept = False
            for info, s in zip(infos, scores):
                if s == max_score and not kept and (info.get("bitrate") or 0) >= max_br:
                    recommendations.append("keep")
                    kept = True
                elif s == max_score and not kept:
                    recommendations.append("manual")
                else:
                    recommendations.append("delete")

    return infos, scores, recommendations, has_warning, None


def run(args: argparse.Namespace) -> None:
    lang = args.lang or CONFIG["LANGUAGE"]
    source = Path(args.source or CONFIG["SOURCE_DIR"])
    dry_run = args.dry_run
    ffprobe = CONFIG["FFPROBE_PATH"]
    recycle_dir = CONFIG["RECYCLE_DIR"]

    logger = setup_logging(CONFIG["LOG_FILE"])

    console.print(Panel(
        f"[bold]{t('source_label', lang)}:[/bold] {source}",
        title=f"[bold cyan]{t('title', lang)}[/bold cyan]",
    ))

    if not check_ffprobe(ffprobe, lang):
        sys.exit(1)

    if not source.exists():
        console.print(f"[red]{t('source_missing', lang, path=source)}[/red]")
        sys.exit(1)

    logger.info(t("log_start", lang, src=source))

    # ── 階段一：掃描（spinner 顯示當前目錄 + 累計影片數）──────────────
    with console.status("") as status:
        def _on_scan(dir_path: str, count: int) -> None:
            # 路徑太長時截短，避免換行
            short = dir_path[-60:] if len(dir_path) > 60 else dir_path
            status.update(f"[cyan]{t('scanning', lang)}[/cyan]  [{count}]  …{short}")

        groups = scan_duplicates(source, CONFIG["VIDEO_EXTENSIONS"], on_progress=_on_scan)

    if not groups:
        console.print(f"\n[green]{t('no_duplicates', lang)}[/green]")
        return

    # ── 階段二：分析（進度條，逐檔 ffprobe）────────────────────────────
    total_to_analyze = sum(len(g) for g in groups)
    all_infos:           List[List[Dict[str, Any]]] = []
    all_scores:          List[List[float]] = []
    all_recs:            List[List[str]] = []
    all_warnings:        List[bool] = []
    all_override_reasons: List[Optional[str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}[/cyan]"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,   # 分析完成後進度條消失，留空間給結果表格
    ) as progress:
        task = progress.add_task("...", total=total_to_analyze)

        for i, group in enumerate(groups, 1):
            def _on_file(p: Path, _i: int = i, _total: int = len(groups)) -> None:
                name = p.name[:45] + "…" if len(p.name) > 46 else p.name
                progress.update(task, description=f"({_i}/{_total}) {name}")
                progress.advance(task)

            infos, scores, recs, warn, override_reason = analyze_group(
                group, ffprobe, on_file=_on_file
            )
            all_infos.append(infos)
            all_scores.append(scores)
            all_recs.append(recs)
            all_warnings.append(warn)
            all_override_reasons.append(override_reason)

    # ── 階段三：顯示所有群組結果表格 ───────────────────────────────────
    total_files = sum(len(g) for g in groups)
    console.print(f"[green]{t('scan_done', lang, groups=len(groups), files=total_files)}[/green]")
    console.print(f"[dim]{t('score_explain', lang)}[/dim]\n")

    for i, (group, infos, scores, recs, warn, override_reason) in enumerate(
        zip(groups, all_infos, all_scores, all_recs, all_warnings, all_override_reasons), 1
    ):
        console.print(f"[bold]{t('group_header', lang, n=i, total=len(groups), stem=group[0].stem)}[/bold]")
        console.print(f"  [dim]{group[0].parent}[/dim]")

        if warn:
            durations = [info["duration"] for info in infos if info["duration"] is not None]
            diff = max(durations) - min(durations) if len(durations) >= 2 else 0
            console.print(f"  [bold yellow]{t('warn_duration', lang, diff=diff)}[/bold yellow]")

        if override_reason == "compat_10bit_av1":
            console.print(f"  [bold magenta]{t('warn_compat', lang)}[/bold magenta]")
        if override_reason == "original_mjpeg":
            console.print(f"  [bold yellow]{t('warn_mjpeg', lang)}[/bold yellow]")

        table = build_group_table(group, infos, scores, recs, lang, override_reason)
        console.print(table)
        console.print()

    # 詢問使用者
    console.print(t("prompt_main", lang))
    choice = Prompt.ask("", choices=["A", "a", "S", "s", "N", "n"], default="N").upper()

    if choice == "N":
        console.print(f"\n[yellow]{t('cancelled', lang)}[/yellow]")
        return

    to_delete: List[Path] = []

    if choice == "A":
        for group, recs in zip(groups, all_recs):
            for path, rec in zip(group, recs):
                if rec == "delete":
                    to_delete.append(path)
    else:  # S
        for i, (group, recs) in enumerate(zip(groups, all_recs), 1):
            delete_candidates = [(path, rec) for path, rec in zip(group, recs) if rec == "delete"]
            for path, _ in delete_candidates:
                ans = Prompt.ask(
                    t("prompt_group", lang, n=i, file=path.name),
                    choices=["y", "Y", "n", "N"],
                    default="N",
                )
                if ans.upper() == "Y":
                    to_delete.append(path)

    if not to_delete:
        console.print(f"\n[yellow]{t('cancelled', lang)}[/yellow]")
        return

    # 執行刪除
    console.print()
    total_freed = 0
    deleted_count = 0
    for path in to_delete:
        freed = delete_file(path, recycle_dir, dry_run, lang, logger)
        total_freed += freed
        deleted_count += 1

    summary = t("summary", lang, deleted=deleted_count, saved=fmt_size(total_freed))
    console.print(f"\n[bold green]{summary}[/bold green]")
    logger.info(t("log_end", lang, deleted=deleted_count, saved=fmt_size(total_freed)))


# ============================================================
# 入口
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Find and clean up duplicate video files")
    parser.add_argument("--source", help="來源目錄（覆蓋 CONFIG）")
    parser.add_argument("--lang", choices=["zh", "en"], help="語言")
    parser.add_argument("--dry-run", action="store_true", help="模擬執行，不真正刪除")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
