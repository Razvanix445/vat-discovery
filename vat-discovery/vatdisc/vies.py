"""
Only businesses that told HMRC they trade goods under the Northern Ireland
Protocol have XI status, so:
    valid   -> the number is live and this is its registered name
    invalid -> says nothing about the GB registration
"""
from __future__ import annotations

import time

import requests

from .hmrc import Check

URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/XI/vat/{vrn}"


def parse(payload: dict, vrn: str) -> Check | None:
    """VIES REST payload -> Check, or None when VIES gave no verdict (e.g. MS_UNAVAILABLE)."""
    verdict = payload.get("userError")
    if verdict == "VALID" and payload.get("isValid"):
        legal, _, _trading = (payload.get("name") or "").partition("!!")
        addr = " ".join((payload.get("address") or "").split())
        return Check(vrn, True, legal.strip(), addr, backend="vies-xi")
    if verdict == "INVALID":
        return Check(vrn, False, backend="vies-xi")
    return None


def check_xi(vrn: str, session: requests.Session | None = None, pause: float = 1.5) -> Check | None:
    s = session or requests.Session()
    for attempt in range(3):
        try:
            r = s.get(URL.format(vrn=vrn), timeout=30)
            got = parse(r.json(), vrn) if r.status_code == 200 else None
        except (requests.RequestException, ValueError):
            got = None
        if got is not None:
            time.sleep(pause)
            return got
        time.sleep(5 * (attempt + 1))
    return None
