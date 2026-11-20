"""Company-name normalisation and match grading.

HMRC's checker returns the name the VAT registration is held under; Companies
House holds the registered company name. For a limited company these are the
same legal string in principle, but in practice differ by punctuation, "LTD" vs
"LIMITED", "&" vs "AND", a leading "THE" or a trading-name suffix.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_SUFFIX = [
    (r"\bLIMITED LIABILITY PARTNERSHIP\b", "LLP"),
    (r"\bPUBLIC LIMITED COMPANY\b", "PLC"),
    (r"\bCOMMUNITY INTEREST COMPANY\b", "CIC"),
    (r"\bCYFYNGEDIG\b", "LTD"),
    (r"\bCYF\b", "LTD"),
    (r"\bLIMITED\b", "LTD"),
    (r"\bCOMPANY\b", "CO"),
    (r"\bCORPORATION\b", "CORP"),
    (r"\bINCORPORATED\b", "INC"),
]
_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")


def canonical(name: str) -> str:
    s = name.upper().replace("&", " AND ").replace("+", " AND ")
    s = re.sub(r"\b(T/A|TRADING AS)\b.*$", "", s)
    s = re.sub(r"[.'’`]", "", s)        # L.T.D. -> LTD, O'NEIL -> ONEIL
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    for pat, rep in _SUFFIX:
        s = re.sub(pat, rep, s)
    s = re.sub(r"^THE ", "", re.sub(r"\s+", " ", s).strip())
    return s


def squashed(name: str) -> str:
    """Canonical form with every space removed and the legal suffix unified."""
    s = canonical(name).replace(" ", "")
    return re.sub(r"(LIMITED|LTD)$", "LTD", s)


def has_company_suffix(name: str) -> bool:
    return bool(re.search(r"\b(LTD|PLC|LLP|CIC)\b", canonical(name)))


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, canonical(a), canonical(b)).ratio()


def grade(a: str, b: str) -> str:
    if not a or not b:
        return "MISMATCH"
    if re.sub(r"\s+", " ", a.upper().strip()) == re.sub(r"\s+", " ", b.upper().strip()):
        return "EXACT"
    ca, cb = canonical(a), canonical(b)
    if ca == cb or squashed(a) == squashed(b):
        return "NORMALISED"
    return "FUZZY" if SequenceMatcher(None, ca, cb).ratio() >= 0.90 else "MISMATCH"


def postcode(text: str) -> str | None:
    """Last UK-shaped postcode in a free-text address, as 'AL7 1GA'."""
    hits = _POSTCODE.findall(text.upper())
    return f"{hits[-1][0]} {hits[-1][1]}" if hits else None


def same_postcode(a: str | None, b: str | None) -> bool:
    pa, pb = postcode(a or ""), postcode(b or "")
    return bool(pa and pb and pa == pb)
