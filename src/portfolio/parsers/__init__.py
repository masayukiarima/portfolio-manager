from __future__ import annotations

import re
from pathlib import Path

from portfolio.models import ParseResult
from portfolio.parsers import rakuten, sbi

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


def detect_broker(html: str) -> str | None:
    if sbi.matches(html):
        return "sbi"
    if rakuten.matches(html):
        return "rakuten"
    return None


def parse_file(path: Path) -> ParseResult:
    raw = path.read_bytes()
    html = decode_html(raw)
    broker = detect_broker(html)
    if broker == "sbi":
        result = sbi.parse(html)
    elif broker == "rakuten":
        result = rakuten.parse(html)
    else:
        raise ValueError(f"証券会社を判定できません: {path}")
    for h in result.holdings:
        h.source_file = path.name
    return result
