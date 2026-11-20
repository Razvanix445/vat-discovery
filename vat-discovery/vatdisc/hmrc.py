"""HMRC verification

It returns a "Check" and both go through a JSON-lines cache so that no
number is ever sent to HMRC twice.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from . import vat

UA = "vat-discovery-research/0.1 (personal research project)"


@dataclass
class Check:
    vrn: str
    valid: bool | None
    name: str = ""
    address: str = ""
    checked_at: str = ""
    backend: str = ""


class Cache:
    def __init__(self, path: str | os.PathLike = "data/hmrc_cache.jsonl") -> None:
        self.path = Path(path)
        self.mem: dict[str, Check] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    c = Check(**json.loads(line))
                    self.mem[c.vrn] = c

    def get(self, vrn: str) -> Check | None:
        return self.mem.get(vrn)

    def put(self, c: Check) -> None:
        if c.valid is None:
            return
        self.mem[c.vrn] = c
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")


class _Throttle:
    def __init__(self, min_interval: float) -> None:
        self.min_interval, self._last = min_interval, 0.0

    def wait(self) -> None:
        gap = self.min_interval - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


class _Base:
    backend = ""

    def __init__(self, cache: Cache | None, min_interval: float) -> None:
        self.cache = cache if cache is not None else Cache()
        self.throttle = _Throttle(min_interval)
        self.calls = 0
        self.rate_limited = 0

    def check(self, vrn: str) -> Check:
        vrn = vat.normalise(vrn) or vrn
        if not vat.is_valid(vrn):
            return Check(vrn, False, backend="checksum")
        hit = self.cache.get(vrn)
        if hit:
            return hit
        c = self._lookup(vrn)
        c.checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        c.backend = self.backend
        self.cache.put(c)
        return c

    def _lookup(self, vrn: str) -> Check:
        raise NotImplementedError


class HmrcApi(_Base):
    backend = "api-v2"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 cache: Cache | None = None, min_interval: float = 0.4) -> None:
        super().__init__(cache, min_interval)
        self.client_id = client_id or os.environ["HMRC_CLIENT_ID"]
        self.client_secret = client_secret or os.environ["HMRC_CLIENT_SECRET"]
        self.base = ("https://test-api.service.hmrc.gov.uk" if os.environ.get("HMRC_SANDBOX")
                     else "https://api.service.hmrc.gov.uk")
        self._token, self._expires = "", 0.0
        self.s = requests.Session()

    def _bearer(self) -> str:
        if time.time() > self._expires - 60:
            r = self.s.post(f"{self.base}/oauth/token", timeout=30, data={
                "grant_type": "client_credentials", "scope": "read:vat",
                "client_id": self.client_id, "client_secret": self.client_secret})
            r.raise_for_status()
            j = r.json()
            self._token, self._expires = j["access_token"], time.time() + int(j.get("expires_in", 3600))
        return self._token

    def _lookup(self, vrn: str) -> Check:
        for attempt in range(5):
            self.throttle.wait()
            r = self.s.get(f"{self.base}/organisations/vat/check-vat-number/lookup/{vrn}", timeout=30,
                           headers={"Accept": "application/vnd.hmrc.2.0+json",
                                    "Authorization": f"Bearer {self._bearer()}"})
            self.calls += 1
            if r.status_code == 200:
                t = r.json()["target"]
                a = t.get("address", {})
                lines = [a.get(f"line{i}", "") for i in range(1, 6)] + [a.get("postcode", ""), a.get("countryCode", "")]
                return Check(vrn, True, t.get("name", ""), " | ".join(x for x in lines if x))
            if r.status_code == 404:
                return Check(vrn, False)
            if r.status_code == 429:
                self.rate_limited += 1
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 401:
                self._expires = 0
                continue
            time.sleep(2 ** attempt)
        return Check(vrn, None)


_RESULT = re.compile(r"Registered business name\s*(.*?)\s*Registered business address\s*(.*?)\s*Search completed", re.S)


def parse_web_result(html: str, vrn: str) -> Check | None:
    """Parse the GOV.UK result page. Returns None if the page is not a result
    for a specific number."""
    m = re.search(r"(?is)<main\b.*?</main>", html)
    if not m:
        return None
    main = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", m.group(0))
    main = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</dd>|</dt>|</h\d>|</li>", "\n", main)
    text = requests.utils.unquote(re.sub(r"<[^>]+>", " ", main))
    import html as _h
    text = _h.unescape(text)
    if vrn not in re.sub(r"\s", "", text):
        return None
    if "VAT registration not found" in text:
        return Check(vrn, False)
    if "Valid UK VAT number" in text:
        r = _RESULT.search(text)
        if not r:
            return None
        name = re.sub(r"\s+", " ", r.group(1)).strip()
        addr = " | ".join(x.strip() for x in re.split(r"\n+", r.group(2)) if x.strip())
        return Check(vrn, True, name, re.sub(r"[ \t]+", " ", addr))
    return None


class HmrcWeb(_Base):
    backend = "web-form"
    URL = "https://www.tax.service.gov.uk/check-vat-number/enter-vat-details"

    def __init__(self, cache: Cache | None = None, min_interval: float = 120.0,
                 cool_off: float = 900.0, sleep=time.sleep) -> None:
        super().__init__(cache, min_interval)
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.cool_off = cool_off
        self.max_refusals = 2
        self._sleep = sleep
        self._consecutive_429 = 0
        self.gave_up = False

    def _token(self) -> str:
        r = self.s.get(self.URL, timeout=30)
        r.raise_for_status()
        m = re.search(r'name="csrfToken"\s+value="([^"]+)"', r.text)
        if not m:
            raise RuntimeError("csrfToken not found on HMRC form")
        return m.group(1)

    def _lookup(self, vrn: str) -> Check:
        if self.gave_up:
            return Check(vrn, None)
        reread = ""
        for _ in range(3):
            self.throttle.wait()
            try:
                if reread:
                    r = self.s.get(reread, timeout=30)
                else:
                    r = self.s.post(self.URL, timeout=30, data={"csrfToken": self._token(), "target": vrn})
            except requests.RequestException:
                self._sleep(60)
                continue
            self.calls += 1
            if r.status_code == 429:
                self.rate_limited += 1
                self._consecutive_429 += 1
                if self._consecutive_429 >= self.max_refusals:
                    self.gave_up = True
                    return Check(vrn, None)
                if r.url.rsplit("/", 1)[-1] in ("known", "unknown"):
                    reread = r.url
                self._sleep(self.cool_off)
                continue
            parsed = parse_web_result(r.text, vrn) if r.ok else None
            if parsed:
                self._consecutive_429 = 0
                return parsed
            reread = ""
            self._sleep(30)
        return Check(vrn, None)


def default_verifier(cache: Cache | None = None) -> _Base:
    """API if credentials are configured, otherwise the throttled public form."""
    if os.environ.get("HMRC_CLIENT_ID") and os.environ.get("HMRC_CLIENT_SECRET"):
        return HmrcApi(cache=cache)
    return HmrcWeb(cache=cache)
