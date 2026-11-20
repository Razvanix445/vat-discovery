"""
Companies House: the sampling frame and the join target.
"""
from __future__ import annotations

import csv
import io
import random
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import names

KEEP = {
    "CompanyName": "name", "CompanyNumber": "crn", "RegAddress.PostCode": "postcode",
    "RegAddress.PostTown": "town", "CompanyCategory": "category", "CompanyStatus": "status",
    "Accounts.AccountCategory": "accounts", "IncorporationDate": "incorporated",
    "SICCode.SicText_1": "sic", "URI": "uri",
}


@dataclass
class Company:
    crn: str
    name: str
    postcode: str = ""
    town: str = ""
    category: str = ""
    status: str = ""
    accounts: str = ""
    incorporated: str = ""
    sic: str = ""
    uri: str = ""
    previous: tuple = ()


def iter_companies(zip_path: str | Path) -> Iterator[Company]:
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            if not member.lower().endswith(".csv"):
                continue
            with z.open(member) as fh:
                rd = csv.reader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
                header = [h.strip() for h in next(rd)]
                idx = {KEEP[h]: i for i, h in enumerate(header) if h in KEEP}
                for row in rd:
                    try:
                        yield Company(**{k: row[i].strip() for k, i in idx.items()})
                    except (IndexError, TypeError):
                        continue


def stratum(c: Company) -> str:
    a = c.accounts.upper()
    if "DORMANT" in a:
        return "dormant"
    if "NO ACCOUNTS FILED" in a or not a:
        return "no accounts yet"
    if "MICRO" in a:
        return "micro"
    if "TOTAL EXEMPTION" in a or "SMALL" in a or "UNAUDITED" in a:
        return "small"
    if "FULL" in a or "GROUP" in a or "MEDIUM" in a or "AUDITED" in a:
        return "medium/large"
    return "other"


def sample(zip_path: str | Path, n: int, seed: int = 20261114, active_only: bool = True) -> list[Company]:
    """Uniform reservoir sample of "n" companies."""
    rng = random.Random(seed)
    res: list[Company] = []
    seen = 0
    for c in iter_companies(zip_path):
        if active_only and c.status.lower() != "active":
            continue
        seen += 1
        if len(res) < n:
            res.append(c)
        else:
            j = rng.randrange(seen)
            if j < n:
                res[j] = c
    return res


class NameIndex:
    """squashed(name) -> [Company]  (case, punctuation, spacing and LTD/LIMITED ignored)."""

    def __init__(self, zip_path: str | Path, wanted: set[str] | None = None,
                 wanted_crns: set[str] | None = None) -> None:
        self.by_name: dict[str, list[Company]] = defaultdict(list)
        self.by_crn: dict[str, Company] = {}
        want = {names.squashed(w) for w in wanted} if wanted is not None else None
        for c in iter_companies(zip_path):
            key = names.squashed(c.name)
            if want is None or key in want:
                self.by_name[key].append(c)
            if wanted_crns is not None and c.crn in wanted_crns:
                self.by_crn[c.crn] = c

    @classmethod
    def from_companies(cls, companies: list[Company]) -> "NameIndex":
        """Small index from records already looked up one by one so results can be recomputed without the bulk file."""
        self = cls.__new__(cls)
        self.by_name, self.by_crn = defaultdict(list), {}
        for c in companies:
            self.by_name[names.squashed(c.name)].append(c)
            self.by_crn[c.crn] = c
        return self

    def resolve(self, name: str) -> list[Company]:
        return self.by_name.get(names.squashed(name), [])
