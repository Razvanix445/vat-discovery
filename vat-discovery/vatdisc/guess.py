"""Guess where a company's website might live, from nothing but its name.

Companies House publishes no websites, so the forward direction (company -> site) has to start from a guess.
"""
from __future__ import annotations

import re

from . import names

_DROP = {"LTD", "PLC", "LLP", "CIC", "LP", "UK", "GB", "HOLDINGS", "GROUP", "INTERNATIONAL"}


def labels(company_name: str) -> list[str]:
    """Domain labels to try, most specific first: 'jsmithbuilding', 'j-smith-building'."""
    s = re.sub(r"\([^)]*\)", " ", company_name)
    toks = [t.lower() for t in names.canonical(s).split() if t not in _DROP]
    toks = [("and" if t == "and" else t) for t in toks]
    if not toks or sum(len(t) for t in toks) < 4:
        return []
    out = ["".join(toks)]
    if len(toks) > 1:
        out.append("-".join(toks))
        no_and = [t for t in toks if t != "and"]
        if no_and != toks and no_and:
            out.append("".join(no_and))
    return [l for i, l in enumerate(out) if 3 < len(l) <= 63 and l not in out[:i]]


def surt_hosts(company_name: str, tlds: tuple[str, ...] = ("uk,co", "com", "uk")) -> list[str]:
    """SURT host keys as used by the Common Crawl index, e.g. 'uk,co,acmewidgets'."""
    return [f"{t},{l}" for l in labels(company_name) for t in tlds]


def surt_to_host(surt: str) -> str:
    return ".".join(reversed(surt.split(",")))
