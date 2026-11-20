"""
A standard VRN is 9 digits: a 7-digit body and 2 check digits.

    S = 8*d1 + 7*d2 + 6*d3 + 5*d4 + 4*d5 + 3*d6 + 2*d7

- "mod 97"   scheme (original):              (S + check) % 97 == 0
- "mod 9755" scheme (numbers issued from
  about 2010 when the mod-97 range ran low): (S + 55 + check) % 97 == 0
"""
from __future__ import annotations

import re

WEIGHTS = (8, 7, 6, 5, 4, 3, 2)
_DIGITS9 = re.compile(r"^\d{9}$")


def _weighted_sum(body7: str) -> int:
    return sum(w * int(c) for w, c in zip(WEIGHTS, body7))


def normalise(raw: str) -> str | None:
    """'GB 220 4302 31' -> '220430231'.  Returns None if not 9 digits.

    12-digit branch-trader numbers (9 + 3-digit branch suffix) are reduced to
    their 9-digit stem. GD/HA government/health-authority formats are ignored
    because they are not companies.
    """
    s = re.sub(r"[\s.\-]", "", raw.upper())
    if s.startswith("GB") or s.startswith("XI"):
        s = s[2:]
    if re.fullmatch(r"\d{12}", s):
        s = s[:9]
    return s if _DIGITS9.match(s) else None


def scheme(vrn: str) -> str | None:
    """Return 'mod97', 'mod9755' or None."""
    if not _DIGITS9.match(vrn) or vrn[:7] == "0000000":
        return None
    check = int(vrn[7:])
    if not 1 <= check <= 97:
        return None
    total = _weighted_sum(vrn[:7]) + check
    if total % 97 == 0:
        return "mod97"
    if (total + 55) % 97 == 0:
        return "mod9755"
    return None


def is_valid(vrn: str) -> bool:
    return scheme(vrn) is not None


def check_digits(body7: str, which: str = "mod97") -> str:
    """The unique 2-digit check pair for a 7-digit body under a scheme."""
    s = _weighted_sum(body7) + (55 if which == "mod9755" else 0)
    cd = 97 - (s % 97)
    return f"{cd:02d}"


def both_candidates(body7: str) -> tuple[str, str]:
    return body7 + check_digits(body7, "mod97"), body7 + check_digits(body7, "mod9755")


def _mulberry32(seed: int):
    a = seed & 0xFFFFFFFF
    while True:
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        yield ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
