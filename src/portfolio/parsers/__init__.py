from __future__ import annotations

import re
from pathlib import Path

from portfolio.models import ParseResult
from portfolio.parsers import rakuten, rakuten_orders, sbi, sbi_funds, sbi_orders

_CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.I)


def decode_html(raw: bytes) -> str:
    """meta charset を優先し、無ければ utf-8 → euc_jp → cp932 の順に試す。"""
    m = _CHARSET_RE.search(raw[:4096])
    candidates: list[str] = []
    if m:
        candidates.append(m.group(1).decode("ascii").lower().replace("shift_jis", "cp932"))
    candidates += ["utf-8", "euc_jp", "cp932"]
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def detect(html: str) -> tuple[str, str] | None:
    """(broker, kind) を返す。kind は "holdings" | "orders" | "funds"。判定できなければ None。"""
    if sbi_funds.matches(html):
        return "sbi", "funds"
    if sbi_orders.matches(html):
        return "sbi", "orders"
    if rakuten_orders.matches(html):
        return "rakuten", "orders"
    if sbi.matches(html):
        return "sbi", "holdings"
    if rakuten.matches(html):
        return "rakuten", "holdings"
    return None


def detect_broker(html: str) -> str | None:
    d = detect(html)
    return d[0] if d else None


def parse_html(html: str, year_hint: int | None = None) -> ParseResult:
    d = detect(html)
    if d is None:
        raise ValueError("証券会社・画面種別を判定できません（保有商品一覧 / 注文照会 のページを保存してください）")
    broker, kind = d
    if (broker, kind) == ("sbi", "holdings"):
        return sbi.parse(html)
    if (broker, kind) == ("sbi", "orders"):
        return sbi_orders.parse(html)
    if (broker, kind) == ("sbi", "funds"):
        return sbi_funds.parse(html)
    if (broker, kind) == ("rakuten", "holdings"):
        return rakuten.parse(html, year_hint=year_hint)
    return rakuten_orders.parse(html, year_hint=year_hint)


def parse_file(path: Path) -> ParseResult:
    result = parse_html(decode_html(path.read_bytes()))
    for r in result.records:
        r.source_file = path.name
    return result
