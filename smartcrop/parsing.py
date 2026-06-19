"""
Page-expression parsing and page-mode → index resolution. Pure, unit-testable.
All indices 0-based internally; UI page modes are 1-based (spec §4.5).
"""
from __future__ import annotations

from typing import List, Optional, Set


def parse_page_expr(expr: str, total: int) -> List[int]:
    """Mixed page expression → sorted 0-based indices.
    Python-native start:stop:step plus comma-separated mix. Negative = from end.
    """
    result: Set[int] = set()
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("Empty page expression.")

    def _pi(s: str) -> Optional[int]:
        s = s.strip()
        return None if s == "" else int(s)

    for tok in expr.split(","):
        tok = tok.strip()
        if not tok:
            continue
        parts = tok.split(":")
        n = len(parts)
        if n == 1:
            raw = parts[0].strip()
            if raw == "":
                result.update(range(total))
            else:
                v = int(raw)
                if v < 0:
                    v = total + v
                if 0 <= v < total:
                    result.add(v)
        elif n == 2:
            result.update(range(total)[slice(_pi(parts[0]), _pi(parts[1]))])
        elif n == 3:
            step = _pi(parts[2])
            if step == 0:
                raise ValueError("Slice step cannot be zero.")
            result.update(range(total)[slice(_pi(parts[0]), _pi(parts[1]), step)])
        else:
            raise ValueError(f"Too many colons in token: {tok!r}")
    return sorted(result)


def parse_selection(expr: str, total: int) -> List[int]:
    """1-indexed human page selection → sorted 0-based indices.
    Accepts comma-separated page numbers and inclusive ranges: '1,3,5-9,12'.
    Out-of-range values are ignored. Empty raises ValueError.
    """
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("Empty page selection.")
    out: Set[int] = set()
    for tok in expr.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok.lstrip("-"):            # a-b range (not a leading minus)
            a, _, b = tok.partition("-")
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            for p in range(lo, hi + 1):
                if 1 <= p <= total:
                    out.add(p - 1)
        else:
            p = int(tok)
            if 1 <= p <= total:
                out.add(p - 1)
    return sorted(out)


def pages_for_mode(mode: str, total: int, current: int, select_expr: str = "") -> List[int]:
    """Resolve a PAGES button selection to 0-based indices.
    'odd'/'even' are 1-indexed page numbers (odd = pages 1,3,5 → idx 0,2,4).
    'select' parses a 1-indexed expression like '1,3,5-9'.
    """
    if total <= 0:
        return []
    if mode == "all":
        return list(range(total))
    if mode == "odd":                        # pages 1,3,5 (1-based) -> idx 0,2,4
        return list(range(0, total, 2))
    if mode == "even":                       # pages 2,4,6 (1-based) -> idx 1,3,5
        return list(range(1, total, 2))
    if mode == "select":
        return parse_selection(select_expr, total)
    raise ValueError(f"Unknown pages mode: {mode!r}")
