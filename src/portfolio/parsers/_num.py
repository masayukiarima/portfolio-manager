"""数値・通貨文字列のパース共通処理。"""
from __future__ import annotations

import re
from typing import Optional

_NUM_RE = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?")
_CURRENCY_WORDS = {
    "円": "JPY", "USD": "USD", "米ドル": "USD", "USドル": "USD",
    "EUR": "EUR", "GBP": "GBP", "AUD": "AUD", "CAD": "CAD", "HKD": "HKD",
    "SGD": "SGD", "CNY": "CNY", "KRW": "KRW", "VND": "VND", "IDR": "IDR",
    "THB": "THB", "MYR": "MYR", "RUB": "RUB",
}


def to_float(text: str | None) -> Optional[float]:
    """先頭の数値トークンを float に。'-' や空は None。"""
    if not text:
        return None
    m = _NUM_RE.search(text)
    if not m:
        return None
    return float(m.group(0).replace(",", "").replace("+", ""))


def all_floats(text: str | None) -> list[float]:
    if not text:
        return []
    return [float(t.replace(",", "").replace("+", "")) for t in _NUM_RE.findall(text)]


def currency_of(text: str | None, default: str = "JPY") -> str:
    if not text:
        return default
    for word, code in _CURRENCY_WORDS.items():
        if word in text:
            return code
    return default
