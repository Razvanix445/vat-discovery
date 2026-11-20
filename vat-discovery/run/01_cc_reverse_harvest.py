from __future__ import annotations

import argparse
import time

from common import DATA, append_jsonl, read_jsonl, seeded_indices
from vatdisc import cc, extract


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawl", default="CC-MAIN-2026-43")
    ap.add_argument("--prefix", default="uk,co,")
    ap.add_argument("--blocks", type=int, default=200)
    ap.add_argument("--seed", type=int, default=43)
    a = ap.parse_args()

    out = DATA / "cc_hosts.jsonl"
    done = {r["block"] for r in read_jsonl(out) if r.get("type") == "block_done"}
    crawl = cc.CommonCrawl(a.crawl)
    blocks = crawl.blocks(a.prefix)
    print(f"{len(blocks):,} index blocks under '{a.prefix}' in {a.crawl}")
    append_jsonl(out, {"type": "frame", "crawl": a.crawl, "prefix": a.prefix, "population_blocks": len(blocks)})

    t0 = time.time()
    for n, bi in enumerate(seeded_indices(len(blocks), a.blocks, a.seed), 1):
        if bi in done:
            continue
        hosts = cc.hosts_starting_in(crawl.captures(blocks[bi]))
        with_vat = with_pages = 0
        for host, caps in hosts.items():
            agg, pages = extract.Extraction(), 0
            for cap in cc.pick_pages(caps):
                try:
                    agg.merge(extract.extract_html(crawl.fetch_html(cap)))
                    pages += 1
                except Exception as e:
                    print(f"   ! {host}: {e}")
            with_vat += bool(agg.vat)
            with_pages += bool(pages)
            append_jsonl(out, {"type": "host", "block": bi, "host": host, "captures": len(caps), "pages": pages,
                               "vat": {v: sorted(t) for v, t in agg.vat.items()}, "crn": agg.crn,
                               "negative": agg.negative, "title": agg.title})
        append_jsonl(out, {"type": "block_done", "block": bi, "hosts": len(hosts), "with_pages": with_pages})
        print(f"[{n}/{a.blocks}] block {bi}: {len(hosts)} hosts, {with_vat} with a VAT candidate "
              f"| {crawl.bytes/1e6:.0f} MB, throttled {crawl.throttled}x, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
