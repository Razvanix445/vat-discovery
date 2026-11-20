"""Common Crawl access without a cluster.

Common Crawl's URL index is sorted by SURT key ("uk,co,example)/path"),
so every .uk capture sits in one contiguous slice. "cluster.idx" maps
key ranges to 3,000-line gzip blocks; a binary search over it by HTTP
Range finds the slice for any prefix without downloading the file.
"""
from __future__ import annotations

import gzip
import io
import json
import time
import zlib
from dataclasses import dataclass

import requests

DATA = "https://data.commoncrawl.org"
UA = "vat-discovery-research/0.1 (personal research project)"


@dataclass
class Block:
    key: str
    file: str
    offset: int
    length: int


class CommonCrawl:
    def __init__(self, crawl: str = "CC-MAIN-2026-43", min_interval: float = 1.0) -> None:
        self.crawl = crawl
        self.base = f"{DATA}/cc-index/collections/{crawl}/indexes/"
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.min_interval = min_interval
        self._last = 0.0
        self.bytes = 0
        self.throttled = 0

    # low level
    def _range(self, url: str, start: int, end: int) -> bytes:
        for attempt in range(8):
            gap = self.min_interval - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()
            try:
                r = self.s.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=60)
            except requests.RequestException:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code in (200, 206):
                self.bytes += len(r.content)
                return r.content
            if r.status_code in (403, 429, 503):
                self.throttled += 1
                time.sleep(min(300, 15 * 2 ** attempt))
                continue
            r.raise_for_status()
        raise RuntimeError(f"gave up on {url} [{start}-{end}]")

    def _idx_size(self) -> int:
        r = self.s.head(self.base + "cluster.idx", timeout=60)
        r.raise_for_status()
        return int(r.headers["Content-Length"])

    def _key_at(self, off: int) -> str:
        chunk = self._range(self.base + "cluster.idx", off, off + 4000).decode("utf-8", "replace")
        lines = chunk.split("\n")
        return lines[1] if len(lines) > 2 else "￿"

    def _lower_bound(self, prefix: str, size: int) -> int:
        lo, hi = 0, size
        while hi - lo > 4000:
            mid = (lo + hi) // 2
            if self._key_at(mid) < prefix:
                lo = mid
            else:
                hi = mid
        return lo

    # public
    def blocks(self, surt_prefix: str = "uk,co,") -> list[Block]:
        """All index blocks whose first key starts with "surt_prefix"."""
        size = self._idx_size()
        a = self._lower_bound(surt_prefix, size)
        b = self._lower_bound(surt_prefix[:-1] + chr(ord(surt_prefix[-1]) + 1), size)
        text = self._range(self.base + "cluster.idx", a, min(size - 1, b + 4000)).decode("utf-8", "replace")
        out = []
        for line in text.split("\n")[1:]:
            parts = line.split("\t")
            if len(parts) >= 4 and parts[0].startswith(surt_prefix):
                out.append(Block(parts[0].split(" ")[0], parts[1], int(parts[2]), int(parts[3])))
        return out

    def captures(self, b: Block) -> list[dict]:
        raw = self._range(self.base + b.file, b.offset, b.offset + b.length - 1)
        rows = []
        for line in gzip.decompress(raw).decode("utf-8", "replace").splitlines():
            i = line.find(" ")
            j = line.find(" ", i + 1)
            try:
                o = json.loads(line[j + 1:])
            except ValueError:
                continue
            o["k"] = line[:i]
            rows.append(o)
        return rows

    def fetch_html(self, cap: dict) -> str:
        """Body of one capture (WARC record -> HTTP response -> payload)."""
        off, ln = int(cap["offset"]), int(cap["length"])
        raw = self._range(f"{DATA}/{cap['filename']}", off, off + ln - 1)
        rec = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
        i = rec.find(b"\r\n\r\n")
        j = rec.find(b"\r\n\r\n", i + 4)
        body = rec[j + 4:]
        enc = (cap.get("encoding") or "utf-8").lower()
        try:
            return body.decode(enc, "replace")
        except LookupError:
            return body.decode("utf-8", "replace")


class HostLookup:
    """
    Loads the whole of cluster.idx once (104 MB, cached on disk) and bisects it
    in memory, so one host lookup costs one block fetch (~270 KB).
    """

    def __init__(self, crawl: CommonCrawl, cache_dir: str = "data") -> None:
        import bisect
        import os
        self._bisect = bisect
        self.crawl = crawl
        path = os.path.join(cache_dir, f"cluster-{crawl.crawl}.idx")
        if not os.path.exists(path):
            print("downloading cluster.idx (104 MB, once) ...")
            with crawl.s.get(crawl.base + "cluster.idx", stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(path + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(path + ".part", path)
        self.keys: list[str] = []
        self.blocks: list[Block] = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 4:
                    k = parts[0].split(" ")[0]
                    self.keys.append(k)
                    self.blocks.append(Block(k, parts[1], int(parts[2]), int(parts[3])))
        self._cache: dict[int, list[dict]] = {}

    def block_index(self, surt_host: str) -> int:
        return max(0, self._bisect.bisect_right(self.keys, surt_host + ")/") - 1)

    def captures_for(self, surt_host: str) -> list[dict]:
        """HTML captures (status 200) for a host; [] if the host is not in the crawl."""
        i = self.block_index(surt_host)
        if i not in self._cache:
            if len(self._cache) > 64:
                self._cache.pop(next(iter(self._cache)))
            self._cache[i] = self.crawl.captures(self.blocks[i])
        pre = surt_host + ")"
        return [r for r in self._cache[i] if r["k"].startswith(pre)
                and r.get("status") == "200" and "html" in (r.get("mime") or "")]


LEGAL_HINT = ("terms", "condition", "privacy", "legal", "contact", "about", "imprint",
              "company-info", "disclaimer", "cookie")


def hosts_starting_in(rows: list[dict]) -> dict[str, list[dict]]:
    """Group a block's captures by host, keeping only hosts that start here."""
    if not rows:
        return {}
    first_host = rows[0]["k"].split(")")[0]
    first_is_start = rows[0]["k"].endswith(")/")
    out: dict[str, list[dict]] = {}
    for r in rows:
        h = r["k"].split(")")[0]
        if h == first_host and not first_is_start:
            continue
        out.setdefault(h, [])
        if r.get("status") == "200" and "html" in (r.get("mime") or ""):
            out[h].append(r)
    return out


def pick_pages(caps: list[dict], max_bytes: int = 600_000) -> list[dict]:
    """Home page (shortest key) + the shortest legal-looking URL."""
    caps = [c for c in caps if int(c.get("length", 0)) < max_bytes]
    if not caps:
        return []
    home = min(caps, key=lambda c: len(c["k"]))
    legal = [c for c in caps if c is not home and any(h in c["url"].lower() for h in LEGAL_HINT)]
    return [home] + ([min(legal, key=lambda c: len(c["url"]))] if legal else [])
