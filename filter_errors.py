#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
filter_errors.py — transcode_av1 錯誤日誌篩選工具
===================================================
從 transcode_state.json 與 log.txt 中篩選、分析、輸出特定記錄。

用法範例
--------
  # 顯示所有失敗記錄（從狀態檔）
  python filter_errors.py --status failed

  # 顯示包含特定錯誤關鍵字的記錄
  python filter_errors.py --status failed --error "subtitle"

  # 篩選特定日期之後的記錄
  python filter_errors.py --status failed --since 2026-05-17

  # 篩選特定路徑的記錄
  python filter_errors.py --match "*.MOV" --status failed

  # 只輸出檔案路徑（方便用於其他腳本）
  python filter_errors.py --status failed --paths-only

  # 顯示統計摘要
  python filter_errors.py --summary

  # 清除失敗記錄，讓下次 transcode_av1.py 重試
  python filter_errors.py --reset-failed

  # 清除特定路徑的記錄（強制重試）
  python filter_errors.py --reset --match "\\\\192.168.3.8\\james\\某個資料夾"

  # 從 log.txt 分析 ERROR 行
  python filter_errors.py --from-log --status error

  # 輸出到檔案
  python filter_errors.py --status failed --output failed_list.txt
"""

import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from fnmatch import fnmatch
from typing import Dict, List, Optional, Tuple

# 預設路徑（與 transcode_av1.py 保持一致）
_BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STATE = str(_BASE_DIR / "transcode_state.json")
DEFAULT_LOG   = str(_BASE_DIR / "log.txt")

try:
    from rich.console import Console
    from rich.table import Table
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def make_console(output_file: Optional[str] = None):
    if _HAS_RICH:
        if output_file:
            return Console(file=open(output_file, "w", encoding="utf-8"), highlight=False)
        return Console()
    return None


def plain_print(msg: str, file=None) -> None:
    print(msg, file=file or sys.stdout)


# ---------- 狀態檔讀取 ----------

def load_state(state_path: str) -> Dict[str, Dict]:
    p = Path(state_path)
    if not p.exists():
        print(f"[錯誤] 找不到狀態檔: {state_path}", file=sys.stderr)
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("processed", {})


def save_state_processed(state_path: str, processed: Dict[str, Dict]) -> None:
    p = Path(state_path)
    with open(p, "r", encoding="utf-8") as f:
        full = json.load(f)
    full["processed"] = processed
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


# ---------- Log 檔讀取 ----------

_LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)"
    r"\s+\[(?P<level>\w+)\]"
    r"\s+(?P<msg>.+)$"
)

def parse_log(log_path: str) -> List[Dict]:
    p = Path(log_path)
    if not p.exists():
        print(f"[錯誤] 找不到日誌檔: {log_path}", file=sys.stderr)
        sys.exit(1)
    entries = []
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _LOG_RE.match(line.rstrip())
            if not m:
                continue
            ts_str = m.group("ts").replace(",", ".")
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                ts = None
            msg = m.group("msg")
            # 嘗試解析 [成功]/[跳過]/[失敗]/[success]/[skipped]/[failed]/... | path | reason
            status = None
            path = None
            reason = None
            pipe_parts = msg.split(" | ", 1)
            prefix = pipe_parts[0].strip()
            if len(pipe_parts) == 2:
                reason = pipe_parts[1].strip()
            for tag, st in [
                ("[成功]", "success"), ("[跳過]", "skipped"), ("[失敗]", "failed"),
                ("[success]", "success"), ("[skipped]", "skipped"), ("[failed]", "failed"),
                ("[éxito]", "success"), ("[omitido]", "skipped"), ("[fallido]", "failed"),
                ("[スキップ]", "skipped"),
            ]:
                if prefix.startswith(tag):
                    status = st
                    path = prefix[len(tag):].strip()
                    break
            entries.append({
                "ts": ts,
                "level": m.group("level").upper(),
                "msg": msg,
                "status": status,
                "path": path,
                "reason": reason,
            })
    return entries


# ---------- 篩選函數 ----------

def parse_date(s: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"無法解析日期: {s}（請用 YYYY-MM-DD 格式）")


def match_path(path: str, pattern: Optional[str]) -> bool:
    if not pattern:
        return True
    return fnmatch(path.lower(), f"*{pattern.lower()}*") or fnmatch(path, pattern)


def filter_state_entries(
    processed: Dict[str, Dict],
    status_filter: Optional[str],
    since: Optional[datetime],
    until: Optional[datetime],
    path_pattern: Optional[str],
    error_keyword: Optional[str],
) -> List[Tuple[str, Dict]]:
    results = []
    for path, rec in processed.items():
        if status_filter and status_filter != "all":
            if rec.get("status", "") != status_filter:
                continue

        if since or until:
            ts_str = rec.get("time", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                ts = None
            if ts:
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue

        if path_pattern and not match_path(path, path_pattern):
            continue

        if error_keyword:
            reason = rec.get("reason", "")
            if error_keyword.lower() not in reason.lower():
                continue

        results.append((path, rec))

    results.sort(key=lambda x: x[1].get("time", ""))
    return results


def filter_log_entries(
    entries: List[Dict],
    level_filter: Optional[str],
    status_filter: Optional[str],
    since: Optional[datetime],
    until: Optional[datetime],
    path_pattern: Optional[str],
    error_keyword: Optional[str],
) -> List[Dict]:
    results = []
    for e in entries:
        if level_filter and level_filter != "all":
            if e["level"].lower() != level_filter.lower():
                continue

        if status_filter and status_filter != "all":
            if e.get("status", "") != status_filter:
                continue

        if since or until:
            ts = e.get("ts")
            if ts:
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue

        if path_pattern:
            path = e.get("path", "") or ""
            if not match_path(path, path_pattern):
                continue

        if error_keyword:
            msg = e.get("msg", "")
            if error_keyword.lower() not in msg.lower():
                continue

        results.append(e)
    return results


# ---------- 輸出 ----------

def format_size(size_bytes: float) -> str:
    size = abs(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:,.2f} {unit}"
        size /= 1024.0
    return f"{size:,.2f} PB"


def print_state_results(
    results: List[Tuple[str, Dict]],
    paths_only: bool,
    out_file=None,
) -> None:
    w = out_file or sys.stdout
    for path, rec in results:
        if paths_only:
            print(path, file=w)
            continue
        ts = rec.get("time", "")[:19]
        status = rec.get("status", "?")
        reason = rec.get("reason", "")
        saved = rec.get("bytes_saved", 0)
        status_sym = {"success": "✓", "skipped": "↷", "failed": "✗"}.get(status, "?")
        saved_str = f"  節省:{format_size(saved)}" if saved else ""
        print(f"[{ts}] {status_sym} {path}", file=w)
        if reason:
            print(f"         原因: {reason}{saved_str}", file=w)


def print_log_results(results: List[Dict], paths_only: bool, out_file=None) -> None:
    w = out_file or sys.stdout
    for e in results:
        if paths_only:
            path = e.get("path") or ""
            if path:
                print(path, file=w)
            continue
        ts = e["ts"].strftime("%Y-%m-%d %H:%M:%S") if e["ts"] else "???"
        level = e["level"]
        msg = e["msg"]
        print(f"[{ts}] [{level}] {msg}", file=w)


def print_summary(processed: Dict[str, Dict], out_file=None) -> None:
    w = out_file or sys.stdout
    counts = {"success": 0, "skipped": 0, "failed": 0, "other": 0}
    total_saved = 0
    for rec in processed.values():
        st = rec.get("status", "other")
        counts[st if st in counts else "other"] += 1
        total_saved += rec.get("bytes_saved", 0)

    print("=" * 50, file=w)
    print(f"  總記錄數  : {sum(counts.values())}", file=w)
    print(f"  成功      : {counts['success']}", file=w)
    print(f"  跳過      : {counts['skipped']}", file=w)
    print(f"  失敗      : {counts['failed']}", file=w)
    print(f"  累計節省  : {format_size(total_saved)}", file=w)
    print("=" * 50, file=w)

    if counts["failed"] > 0:
        print(f"\n  提示：有 {counts['failed']} 筆失敗記錄。", file=w)
        print("  執行以下指令清除並重試：", file=w)
        print("    python filter_errors.py --reset-failed", file=w)
        print("  或直接執行：", file=w)
        print("    python transcode_av1.py --reset-failed", file=w)


# ---------- 主程式 ----------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="transcode_av1 錯誤日誌篩選工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--state", default=DEFAULT_STATE, help="狀態 JSON 檔路徑")
    p.add_argument("--log",   default=DEFAULT_LOG,   help="log.txt 路徑")

    src = p.add_mutually_exclusive_group()
    src.add_argument("--from-state", action="store_true", default=True,
                     help="從狀態 JSON 篩選（預設）")
    src.add_argument("--from-log",   action="store_true",
                     help="從 log.txt 篩選")

    p.add_argument("--status",
                   choices=["success", "skipped", "failed", "all", "error", "warning", "info"],
                   default="failed",
                   help="篩選狀態（預設: failed）")
    p.add_argument("--since",  metavar="YYYY-MM-DD", help="只顯示此日期之後的記錄")
    p.add_argument("--until",  metavar="YYYY-MM-DD", help="只顯示此日期之前的記錄")
    p.add_argument("--match",  metavar="PATTERN",    help="路徑包含此字串（支援 * glob）")
    p.add_argument("--error",  metavar="KEYWORD",    help="原因/訊息包含此關鍵字")

    p.add_argument("--summary",    action="store_true", help="顯示統計摘要後結束")
    p.add_argument("--paths-only", action="store_true", help="只輸出檔案路徑（方便 pipeline）")
    p.add_argument("--output", metavar="FILE",           help="結果寫入此檔案")

    p.add_argument("--reset-failed", action="store_true",
                   help="從狀態檔移除所有失敗記錄（讓 transcode_av1.py 重試）")
    p.add_argument("--reset",        action="store_true",
                   help="搭配 --match，移除符合條件的記錄（強制重試）")

    return p.parse_args()


def main() -> None:
    args = parse_args()

    out_f = None
    if args.output:
        out_f = open(args.output, "w", encoding="utf-8")

    try:
        processed = load_state(args.state)

        # ---- 摘要模式 ----
        if args.summary:
            print_summary(processed, out_file=out_f)
            return

        # ---- 重置模式 ----
        if args.reset_failed:
            keys = [k for k, v in processed.items() if v.get("status") == "failed"]
            for k in keys:
                del processed[k]
            save_state_processed(args.state, processed)
            print(f"已清除 {len(keys)} 筆失敗記錄。")
            return

        if args.reset:
            if not args.match:
                print("[錯誤] --reset 需搭配 --match 指定要清除的路徑", file=sys.stderr)
                sys.exit(1)
            keys = [k for k in processed if match_path(k, args.match)]
            for k in keys:
                del processed[k]
            save_state_processed(args.state, processed)
            print(f"已清除 {len(keys)} 筆記錄（符合 {args.match!r}）。")
            return

        # ---- 日期解析 ----
        since = parse_date(args.since) if args.since else None
        until = parse_date(args.until) if args.until else None

        # ---- 從 log.txt 篩選 ----
        if args.from_log:
            entries = parse_log(args.log)
            level_f = args.status if args.status in ("error", "warning", "info") else None
            status_f = args.status if args.status in ("success", "skipped", "failed") else None
            results = filter_log_entries(
                entries, level_f, status_f, since, until, args.match, args.error
            )
            print(f"符合條件: {len(results)} 筆（log.txt）", file=out_f or sys.stdout)
            print_log_results(results, args.paths_only, out_file=out_f)
            return

        # ---- 從狀態 JSON 篩選（預設）----
        status_f = args.status if args.status in ("success", "skipped", "failed", "all") else "all"
        results = filter_state_entries(
            processed, status_f, since, until, args.match, args.error
        )
        print(f"符合條件: {len(results)} 筆（state JSON）", file=out_f or sys.stdout)
        if not args.paths_only:
            print("-" * 60, file=out_f or sys.stdout)
        print_state_results(results, args.paths_only, out_file=out_f)

        if not args.paths_only and results:
            saved_total = sum(r.get("bytes_saved", 0) for _, r in results)
            if saved_total:
                print(f"\n累計節省：{format_size(saved_total)}", file=out_f or sys.stdout)

    finally:
        if out_f:
            out_f.close()
            print(f"結果已寫入: {args.output}")


if __name__ == "__main__":
    main()
