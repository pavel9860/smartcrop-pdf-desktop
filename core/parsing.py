"""
Page-expression parsing and page-mode → index resolution. Pure, unit-testable.
All indices 0-based internally; UI page modes are 1-based (spec §4.5).
"""
from __future__ import annotations

from typing import List, Optional, Set


def _single_token_indices(raw: str, total: int) -> List[int]:
    """A bare (colon-free) token: '' means the whole range; negative counts from the
    end; out-of-range silently yields nothing."""
    raw = raw.strip()
    if raw == "":
        return list(range(total))
    v = int(raw)
    if v < 0:
        v = total + v
    return [v] if 0 <= v < total else []


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
            result.update(_single_token_indices(parts[0], total))
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


def _colon_slice(tok: str, total: int) -> List[int]:
    """A 1-indexed inclusive colon slice `start:stop[:step]` → 1-based page numbers.

    Ends are optional and default to the full document, so Python-style slices work:
    `1:100:5` → 1,6,…,96; `::2` → every odd page; `10:` → page 10 to the end. A two-part
    `a:b` (no step) is order-agnostic and inclusive (`1:4` == `4:1` == 1,2,3,4); a three-part
    slice honours its step's direction. Out-of-range pages are dropped by the caller.
    """
    parts = tok.split(":")
    if len(parts) > 3:
        raise ValueError(f"Too many colons in token: {tok!r}")

    def gi(s: str, default: int) -> int:
        s = s.strip()
        return default if s == "" else int(s)

    step = gi(parts[2], 1) if len(parts) == 3 else 1
    if step == 0:
        raise ValueError("Slice step cannot be zero.")
    start = gi(parts[0], 1 if step > 0 else total)
    stop = gi(parts[1], total if step > 0 else 1)
    if len(parts) == 2 and step > 0 and start > stop:     # 'a:b' inclusive, order-agnostic
        start, stop = stop, start
    return list(range(start, stop + (1 if step > 0 else -1), step))


def parse_selection(expr: str, total: int) -> List[int]:
    """1-indexed human page selection → sorted 0-based indices.

    Accepts comma-separated page numbers, inclusive ranges with '-', and Python-style
    colon slices `start:stop[:step]` (1-indexed inclusive; '1:4' == '1-4' == pages 1-4,
    '1:100:5' == 1,6,…,96). Mixes like '1:4, 10:30, 35, 37' work. Out-of-range values are
    ignored. Empty raises ValueError.
    """
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("Empty page selection.")
    out: Set[int] = set()
    for tok in expr.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok:                        # start:stop[:step] slice
            pages = _colon_slice(tok, total)
        elif "-" in tok.lstrip("-"):          # a-b inclusive range
            a, _, b = tok.partition("-")
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            pages = list(range(lo, hi + 1))
        else:
            pages = [int(tok)]
        for p in pages:
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
