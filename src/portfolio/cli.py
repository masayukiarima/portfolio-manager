from __future__ import annotations

import argparse
import glob
import sys
from datetime import date, datetime
from pathlib import Path

from portfolio import db as dbmod
from portfolio.models import ParseResult
from portfolio.parsers import decode_html, parse_html

DEFAULT_IMPORT_GLOB = "imports/**/*.html"


def parse_path(path: Path, override: date | None = None) -> tuple[bytes, ParseResult]:
    """ファイルを解析し、スナップショット日付を確定させて返す。"""
    raw = path.read_bytes()
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    # 楽天の画面は年を表示しないため、ファイル更新日時の年で補完する
    result = parse_html(decode_html(raw), year_hint=mtime.year)
    snap = override or result.snapshot_date or mtime.date()
    result.snapshot_date = snap
    for r in result.all_records:
        r.snapshot_date = snap
        r.source_file = path.name
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
    # 「ウェブページ、完全」で保存すると付随する <name>_files/ 配下の HTML は対象外
    return sorted(
        Path(m) for m in glob.glob(pattern, recursive=True)
        if not any(part.endswith("_files") for part in Path(m).parts[:-1])
    )


def cmd_import(args: argparse.Namespace) -> int:
    override = date.fromisoformat(args.date) if args.date else None
    conn = dbmod.connect(Path(args.db))
    status = 0
    patterns = args.files or [DEFAULT_IMPORT_GLOB]
    for pattern in patterns:
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
            # 1ページに複数種別が載ることがある（楽天: holdings+balances、SBI保有証券一覧: holdings+funds）
            parts = [(k, v) for k, v in (("holdings", result.holdings), ("orders", result.orders),
                                         ("funds", result.funds), ("balances", result.balances)) if v]
            label = f"{result.broker} {snap} " + ", ".join(f"{k} {len(v)}件" for k, v in parts)
            if args.dry_run:
                _print_records(result)
                print(f"[dry-run] {path.name}: {label}")
                continue
            n = 0
            for k, v in parts:
                n += {"holdings": dbmod.upsert_holdings, "orders": dbmod.upsert_orders,
                      "funds": dbmod.upsert_funds, "balances": dbmod.upsert_balances}[k](conn, v)
            new_raw = dbmod.record_raw_import(
                conn, snapshot_date=snap.isoformat(), broker=result.broker,
                source_file=path.name, content=raw, row_count=n, kind="+".join(k for k, _ in parts),
            )
            note = "" if new_raw else " (同一内容の再取込)"
            print(f"[ok] {path.name}: {label} 取込{note}")
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


def cmd_orders(args: argparse.Namespace) -> int:
    conn = dbmod.connect(Path(args.db))
    where, params = ("WHERE snapshot_date = ?", (args.date,)) if args.date else ("", ())
    source = "orders" if args.date else "latest_orders"
    rows = conn.execute(
        f"SELECT * FROM {source} {where} ORDER BY broker, ordered_at DESC, order_key", params
    ).fetchall()
    print_orders(rows)
    return 0


def cmd_funds(args: argparse.Namespace) -> int:
    conn = dbmod.connect(Path(args.db))
    where, params = ("WHERE snapshot_date = ?", (args.date,)) if args.date else ("", ())
    source = "funds" if args.date else "latest_funds"
    rows = conn.execute(
        f"SELECT * FROM {source} {where} ORDER BY broker, account_type, name", params
    ).fetchall()
    print_funds(rows)
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


def print_funds(rows) -> None:
    print(f"{'broker':8} {'口座':12} {'N':1} {'積':1} {'口数':>12} {'基準価額':>9} {'取得単価':>9} "
          f"{'評価額(円)':>12} {'損益(円)':>12} {'損益%':>7} {'前日比(円)':>10} ファンド名")
    for r in rows:
        print(f"{_g(r, 'broker'):8} {_g(r, 'account_type'):12} {'*' if _g(r, 'is_nisa') else ' '} "
              f"{'*' if _g(r, 'is_accumulating') else ' '} {_g(r, 'units') or 0:>12,.0f} "
              f"{_g(r, 'nav') or 0:>9,.0f} {_g(r, 'avg_cost') or 0:>9,.0f} "
              f"{_g(r, 'market_value_jpy') or 0:>12,.0f} {_g(r, 'unrealized_pnl_jpy') or 0:>12,.0f} "
              f"{_g(r, 'unrealized_pnl_pct') or 0:>7,.2f} {_g(r, 'day_change_jpy') or 0:>10,.0f} "
              f"{_g(r, 'name')}")


def cmd_balances(args: argparse.Namespace) -> int:
    conn = dbmod.connect(Path(args.db))
    where, params = ("WHERE snapshot_date = ?", (args.date,)) if args.date else ("", ())
    source = "balances" if args.date else "latest_balances"
    rows = conn.execute(
        f"SELECT * FROM {source} {where} ORDER BY broker, is_total, is_cash, category", params
    ).fetchall()
    print_balances(rows)
    cash = conn.execute(
        f"SELECT broker, snapshot_date, ROUND(SUM(market_value_jpy)) cash FROM {source} {where} "
        + ("AND" if where else "WHERE") + " is_cash = 1 AND is_total = 0 GROUP BY broker, snapshot_date",
        params,
    ).fetchall()
    print()
    print(f"{'broker':8} {'date':10} {'現金同等物(円)':>14}")
    for r in cash:
        print(f"{r['broker']:8} {r['snapshot_date']:10} {r['cash'] or 0:>14,.0f}")
    return 0


def print_balances(rows) -> None:
    def num(v, fmt=",.0f"):
        return f"{v:{fmt}}" if v is not None else "-"

    print(f"{'broker':8} {'区分':12} {'C':1} {'評価額(円)':>14} {'損益(円)':>12} {'損益%':>7} "
          f"{'前日比(円)':>11} {'前月比(円)':>11} 画面表記")
    for r in rows:
        print(f"{_g(r, 'broker'):8} {_g(r, 'category'):12} {'*' if _g(r, 'is_cash') else ' '} "
              f"{num(_g(r, 'market_value_jpy')):>14} {num(_g(r, 'unrealized_pnl_jpy')):>12} "
              f"{num(_g(r, 'unrealized_pnl_pct'), ',.2f'):>7} {num(_g(r, 'day_change_jpy')):>11} "
              f"{num(_g(r, 'month_change_jpy')):>11} {_g(r, 'label')}")


def cmd_sql(args: argparse.Namespace) -> int:
    """任意の SQL を実行して結果を表形式（または CSV）で表示する。sqlite3 CLI が無い環境向け。"""
    import csv
    import sqlite3

    conn = dbmod.connect(Path(args.db))
    query = Path(args.file).read_text(encoding="utf-8") if args.file else args.query
    if not query:
        print("SQL を引数か --file で指定してください", file=sys.stderr)
        return 2
    try:
        cur = conn.execute(query)
    except sqlite3.Error as e:
        print(f"SQL error: {e}", file=sys.stderr)
        return 1
    if cur.description is None:  # INSERT/UPDATE 等
        conn.commit()
        print(f"{cur.rowcount} rows affected")
        return 0
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if args.csv:
        w = csv.writer(sys.stdout, lineterminator="\n")
        w.writerow(cols)
        w.writerows(tuple(r) for r in rows)
        return 0
    cells = [[("" if v is None else f"{v:,.2f}" if isinstance(v, float) else str(v)) for v in r] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) if cells else len(c) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(v.ljust(w) for v, w in zip(row, widths)))
    print(f"({len(rows)} rows)")
    return 0


def cmd_dates(args: argparse.Namespace) -> int:
    conn = dbmod.connect(Path(args.db))
    for r in conn.execute(
        "SELECT snapshot_date, broker, 'holdings' kind, COUNT(*) n FROM holdings GROUP BY 1, 2 "
        "UNION ALL "
        "SELECT snapshot_date, broker, 'orders', COUNT(*) FROM orders GROUP BY 1, 2 "
        "UNION ALL "
        "SELECT snapshot_date, broker, 'funds', COUNT(*) FROM funds GROUP BY 1, 2 "
        "UNION ALL "
        "SELECT snapshot_date, broker, 'balances', COUNT(*) FROM balances GROUP BY 1, 2 "
        "ORDER BY 1 DESC, 2, 3"
    ):
        print(f"{r['snapshot_date']}  {r['broker']:8} {r['kind']:8} {r['n']}件")
    return 0


def _g(r, k):
    return r[k] if hasattr(r, "keys") else getattr(r, k)


def _print_records(result: ParseResult) -> None:
    first = True
    for rows, printer in ((result.holdings, print_holdings), (result.orders, print_orders),
                          (result.funds, print_funds), (result.balances, print_balances)):
        if not rows:
            continue
        if not first:
            print()
        printer(rows)
        first = False


def print_holdings(rows) -> None:
    print(f"{'broker':8} {'口座':6} {'N':1} {'種別':8} {'symbol':10} {'数量':>10} "
          f"{'現在値':>10} {'評価額(円)':>12} {'損益(円)':>12} 銘柄名")
    for r in rows:
        print(f"{_g(r, 'broker'):8} {_g(r, 'account_type'):6} {'*' if _g(r, 'is_nisa') else ' '} "
              f"{_g(r, 'asset_class'):8} {_g(r, 'symbol')[:10]:10} {_g(r, 'quantity') or 0:>10,.2f} "
              f"{_g(r, 'price') or 0:>10,.2f} {_g(r, 'market_value_jpy') or 0:>12,.0f} "
              f"{_g(r, 'unrealized_pnl_jpy') or 0:>12,.0f} {_g(r, 'name')}")


def print_orders(rows) -> None:
    print(f"{'broker':8} {'注文番号':6} {'注文日時':16} {'状況':12} {'symbol':6} {'売買':2} {'口座':4} "
          f"{'数量':>6} {'約定':>4} {'種別':10} {'単価':>9} {'逆指値':>9} {'期限':10} 条件")

    def num(v):
        return f"{v:,.2f}" if v is not None else "-"

    for r in rows:
        print(f"{_g(r, 'broker'):8} {(_g(r, 'order_no') or '-'):6} {(_g(r, 'ordered_at') or ''):16} "
              f"{_g(r, 'status'):12} {_g(r, 'symbol'):6} {_g(r, 'side'):2} {_g(r, 'account_type'):4} "
              f"{_g(r, 'quantity') or 0:>6,.0f} {_g(r, 'filled_quantity') or 0:>4,.0f} "
              f"{(_g(r, 'order_type') or ''):10} {num(_g(r, 'limit_price')):>9} "
              f"{num(_g(r, 'trigger_price')):>9} {(_g(r, 'expires_on') or ''):10} {_g(r, 'condition') or ''}")


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(dbmod.DEFAULT_DB), help="SQLiteファイル (既定: portfolio.db)")

    p = argparse.ArgumentParser(prog="portfolio", description="保有商品一覧・注文照会のHTMLをSQLiteに取り込む")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import", help="保存したHTMLを取り込む（保有一覧 / 注文照会 を自動判定）", parents=[common])
    s.add_argument("files", nargs="*", help=f"HTMLファイル (glob可)。省略時は {DEFAULT_IMPORT_GLOB}")
    s.add_argument("--date", help="スナップショット日付を上書き (YYYY-MM-DD)")
    s.add_argument("--dry-run", action="store_true", help="DBに書かず解析結果だけ表示")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("show", help="最新の保有状況を表示", parents=[common])
    s.add_argument("--date", help="表示する日付 (YYYY-MM-DD)")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("orders", help="最新の注文状況を表示", parents=[common])
    s.add_argument("--date", help="表示する日付 (YYYY-MM-DD)")
    s.set_defaults(func=cmd_orders)

    s = sub.add_parser("funds", help="最新の保有ファンド（投資信託）を表示", parents=[common])
    s.add_argument("--date", help="表示する日付 (YYYY-MM-DD)")
    s.set_defaults(func=cmd_funds)

    s = sub.add_parser("balances", help="最新の資産残高サマリ（商品区分別・預り金・銀行残高）を表示", parents=[common])
    s.add_argument("--date", help="表示する日付 (YYYY-MM-DD)")
    s.set_defaults(func=cmd_balances)

    s = sub.add_parser("dates", help="取込済みの日付一覧", parents=[common])
    s.set_defaults(func=cmd_dates)

    s = sub.add_parser("sql", help="任意の SQL を実行して表示（sqlite3 CLI 不要）", parents=[common])
    s.add_argument("query", nargs="?", help="SQL 文")
    s.add_argument("-f", "--file", help="SQL ファイル")
    s.add_argument("--csv", action="store_true", help="CSV で出力")
    s.set_defaults(func=cmd_sql)

    args = p.parse_args(argv)
    return args.func(args)
