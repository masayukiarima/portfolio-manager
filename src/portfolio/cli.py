from __future__ import annotations

import argparse
import glob
import sys
from datetime import date, datetime
from pathlib import Path

from portfolio import db as dbmod
from portfolio.models import ParseResult
from portfolio.parsers import decode_html, detect_broker, rakuten, sbi


def parse_path(path: Path, override: date | None = None) -> tuple[bytes, ParseResult]:
    """ファイルを解析し、スナップショット日付を確定させて返す。"""
    raw = path.read_bytes()
    html = decode_html(raw)
    broker = detect_broker(html)
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    if broker == "sbi":
        result = sbi.parse(html)
    elif broker == "rakuten":
        # 楽天の画面は年を表示しないため、ファイル更新日時の年で補完する
        result = rakuten.parse(html, year_hint=mtime.year)
    else:
        raise ValueError(f"証券会社を判定できません: {path}")
    snap = override or result.snapshot_date or mtime.date()
    result.snapshot_date = snap
    for h in result.holdings:
        h.snapshot_date = snap
        h.source_file = path.name
    return raw, result


def _expand(pattern: str) -> list[Path]:
    """引数をファイル一覧に展開する。

    bash はシェル側で glob を展開して実ファイル名を渡し、PowerShell/cmd は展開せずパターンを
    そのまま渡す。ファイル名に '[PC]' のような glob メタ文字が含まれることがあるため、
    まず実在するパスとして扱い、存在しない場合だけ glob パターンとみなす。
    """
    p = Path(pattern)
    if p.exists():
        return [p]
    return sorted(Path(m) for m in glob.glob(pattern))


def cmd_import(args: argparse.Namespace) -> int:
    override = date.fromisoformat(args.date) if args.date else None
    conn = dbmod.connect(Path(args.db))
    status = 0
    for pattern in args.files:
        paths = _expand(pattern)
        if not paths:
            print(f"[skip] 該当なし: {pattern}", file=sys.stderr)
        for path in paths:
            try:
                raw, result = parse_path(path, override)
            except Exception as e:  # noqa: BLE001
                print(f"[error] {path}: {e}", file=sys.stderr)
                status = 1
                continue
            for w in result.warnings:
                print(f"[warn] {path.name}: {w}", file=sys.stderr)
            snap = result.snapshot_date
            if args.dry_run:
                print_holdings(result.holdings)
                print(f"[dry-run] {path.name}: {result.broker} {snap} {len(result.holdings)}件")
                continue
            n = dbmod.upsert_holdings(conn, result.holdings)
            new_raw = dbmod.record_raw_import(
                conn, snapshot_date=snap.isoformat(), broker=result.broker,
                source_file=path.name, content=raw, row_count=n,
            )
            note = "" if new_raw else " (同一内容の再取込)"
            print(f"[ok] {path.name}: {result.broker} {snap} {n}件 取込{note}")
    return status


def cmd_show(args: argparse.Namespace) -> int:
    conn = dbmod.connect(Path(args.db))
    where, params = ("WHERE snapshot_date = ?", (args.date,)) if args.date else ("", ())
    source = "holdings" if args.date else "latest_holdings"
    rows = conn.execute(
        f"SELECT * FROM {source} {where} ORDER BY broker, account_type, asset_class, symbol", params
    ).fetchall()
    print_holdings(rows)
    summary = conn.execute(
        "SELECT broker, snapshot_date, is_nisa, COUNT(*) n, "
        "ROUND(SUM(market_value_jpy)) mv, ROUND(SUM(unrealized_pnl_jpy)) pnl "
        f"FROM {source} {where} GROUP BY broker, snapshot_date, is_nisa ORDER BY broker, is_nisa",
        params,
    ).fetchall()
    print()
    print(f"{'broker':8} {'date':10} {'nisa':4} {'件数':>4} {'評価額(円)':>14} {'損益(円)':>12}")
    for r in summary:
        print(f"{r['broker']:8} {r['snapshot_date']:10} {r['is_nisa']:>4} {r['n']:>4} "
              f"{r['mv'] or 0:>14,.0f} {r['pnl'] or 0:>12,.0f}")
    return 0


def cmd_dates(args: argparse.Namespace) -> int:
    conn = dbmod.connect(Path(args.db))
    for r in conn.execute(
        "SELECT snapshot_date, broker, COUNT(*) n FROM holdings GROUP BY 1, 2 ORDER BY 1 DESC, 2"
    ):
        print(f"{r['snapshot_date']}  {r['broker']:8} {r['n']}件")
    return 0


def print_holdings(rows) -> None:
    def g(r, k):
        return r[k] if hasattr(r, "keys") else getattr(r, k)

    print(f"{'broker':8} {'口座':6} {'N':1} {'種別':8} {'symbol':10} {'数量':>10} "
          f"{'現在値':>10} {'評価額(円)':>12} {'損益(円)':>12} 銘柄名")
    for r in rows:
        print(f"{g(r, 'broker'):8} {g(r, 'account_type'):6} {'*' if g(r, 'is_nisa') else ' '} "
              f"{g(r, 'asset_class'):8} {g(r, 'symbol')[:10]:10} {g(r, 'quantity') or 0:>10,.2f} "
              f"{g(r, 'price') or 0:>10,.2f} {g(r, 'market_value_jpy') or 0:>12,.0f} "
              f"{g(r, 'unrealized_pnl_jpy') or 0:>12,.0f} {g(r, 'name')}")


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(dbmod.DEFAULT_DB), help="SQLiteファイル (既定: portfolio.db)")

    p = argparse.ArgumentParser(prog="portfolio", description="保有商品一覧HTMLをSQLiteに取り込む")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import", help="保存したHTMLを取り込む", parents=[common])
    s.add_argument("files", nargs="+", help="HTMLファイル (glob可)")
    s.add_argument("--date", help="スナップショット日付を上書き (YYYY-MM-DD)")
    s.add_argument("--dry-run", action="store_true", help="DBに書かず解析結果だけ表示")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("show", help="最新スナップショットを表示", parents=[common])
    s.add_argument("--date", help="表示する日付 (YYYY-MM-DD)")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("dates", help="取込済みの日付一覧", parents=[common])
    s.set_defaults(func=cmd_dates)

    args = p.parse_args(argv)
    return args.func(args)
