"""Peppol Directory: an open address book of e-invoicing participants.

UK businesses that receive or send e-invoices over Peppol (NHS and central
government suppliers above all) are listed with a participant identifier.
For UK entities that identifier is very often "9932:<VAT number>" — ISO 6523
ICD 9932 is "GB VAT number". So the directory is a public list of
(business name, VAT number) pairs that the business itself (or its access
point) published.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator

import requests

URL = "https://directory.peppol.eu/search/1.0/json"
UA = "vat-discovery-research/0.1 (personal research project)"


@dataclass
class Participant:
    scheme: str
    value: str
    name: str
    regdate: str


def parse_matches(payload: dict, regdate: str = "") -> list[Participant]:
    out = []
    for m in payload.get("matches", []):
        pid = m.get("participantID", {}).get("value", "")
        scheme, _, value = pid.partition(":")
        ent = (m.get("entities") or [{}])[0]
        nm = (ent.get("name") or [{}])[0].get("name", "")
        out.append(Participant(scheme, value, nm, ent.get("regDate", "") or regdate))
    return out


def search(session: requests.Session, **params) -> dict:
    for attempt in range(6):
        r = session.get(URL, params={"rpc": 1000, **params}, timeout=60, headers={"User-Agent": UA})
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
    raise RuntimeError("Peppol directory kept rate-limiting")


def harvest_gb(start: date, end: date, pause: float = 0.6) -> Iterator[Participant]:
    s = requests.Session()
    d = start
    while d <= end:
        payload = search(s, country="GB", regdate=d.isoformat())
        yield from parse_matches(payload, d.isoformat())
        d += timedelta(days=1)
        time.sleep(pause)
