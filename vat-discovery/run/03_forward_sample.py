"""
For every company: guess domain names from the registered name, look each
guess up in a fixed Common Crawl snapshot, read the home page and a legal page,
extract candidates, verify with HMRC and accept only if HMRC's registered name is the company's name.

Every company ends in exactly one state:
    FOUND_A / FOUND_B        verified number attributed to this company
    VAT_ON_SITE_REJECTED     a number was on the site but HMRC says it is dead or someone else's
    SITE_CONFIRMED_NO_VAT    a site that prints this company's number or name, and no VAT number
    SITE_UNCONFIRMED         a guessed domain exists but nothing ties it to the company
    NO_SITE                  no guess exists in the crawl
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict

from common import DATA, RESULTS, append_jsonl, find_ch_zip, read_jsonl
from vatdisc import attribute, cc, ch, extract, guess, hmrc, names, stats


def load_sample(a) -> list[dict]:
    path = DATA / f"forward_sample_{a.source}.jsonl"
    if path.exists():
        return read_jsonl(path)
    if a.source == "ch":
        comps = ch.sample(find_ch_zip(), a.n, a.seed)
    else:
        peps = [p for p in read_jsonl(DATA / "peppol_verified.jsonl") if p.get("hmrc_valid")]
        idx = ch.NameIndex(find_ch_zip(), wanted={p["hmrc_name"] for p in peps})
        comps = []
        for p in peps:
            hit = idx.resolve(p["hmrc_name"])
            if len(hit) == 1 and hit[0].status.lower() == "active":
                comps.append(hit[0])
        comps = comps[: a.n]
    out = [dict(crn=c.crn, name=c.name, postcode=c.postcode, stratum=ch.stratum(c), sic=c.sic[:5],
                incorporated=c.incorporated) for c in comps]
    for o in out:
        append_jsonl(path, o)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--source", choices=["ch", "peppol"], default="ch")
    ap.add_argument("--crawl", default="CC-MAIN-2026-43")
    a = ap.parse_args()

    sample = load_sample(a)
    out_path = DATA / f"forward_{a.source}.jsonl"
    done = {r["crn"] for r in read_jsonl(out_path)}
    crawl = cc.CommonCrawl(a.crawl)
    lookup = cc.HostLookup(crawl, str(DATA))
    verifier = hmrc.default_verifier(hmrc.Cache(DATA / "hmrc_cache.jsonl"))

    for n, co in enumerate(sample, 1):
        if co["crn"] in done:
            continue
        rec = dict(co, hosts_tried=0, host="", site="NO_SITE", vat={}, state="NO_SITE", vrn="", tier="")
        best = None
        for surt in guess.surt_hosts(co["name"]):
            rec["hosts_tried"] += 1
            caps = lookup.captures_for(surt)
            if not caps:
                continue
            agg, text = extract.Extraction(), ""
            for cap in cc.pick_pages(caps):
                try:
                    html = crawl.fetch_html(cap)
                except Exception:
                    continue
                agg.merge(extract.extract_html(html))
                text += " " + extract.html_to_text(html)[0]
            if co["crn"] in agg.crn:
                site = "CRN"
            elif names.canonical(co["name"]) in names.canonical(text):
                site = "NAME"
            else:
                site = "UNCONFIRMED"
            rank = {"CRN": 3, "NAME": 2, "UNCONFIRMED": 1}[site] + (0.5 if agg.vat else 0)
            if best is None or rank > best[0]:
                best = (rank, surt, site, agg)
            if site == "CRN" and agg.vat:
                break
        if best:
            _, surt, site, agg = best
            rec.update(host=guess.surt_to_host(surt), site=site, vat={v: sorted(t) for v, t in agg.vat.items()},
                       negative=agg.negative)
            rec["state"] = "SITE_UNCONFIRMED" if site == "UNCONFIRMED" else "SITE_CONFIRMED_NO_VAT"
            for v in agg.vat:
                c = verifier.check(v)
                verdict = attribute.judge(c.valid, c.name, c.address, co["name"], co["postcode"],
                                          page_has_crn=(site == "CRN"))
                if verdict.tier in ("A", "B"):
                    rec.update(state=f"FOUND_{verdict.tier}", vrn=v, tier=verdict.tier, hmrc_name=c.name)
                    break
                rec.setdefault("rejected", []).append([v, c.valid, c.name, verdict.reason])
            if rec.get("rejected") and not rec["state"].startswith("FOUND"):
                rec["state"] = "VAT_ON_SITE_REJECTED"
        append_jsonl(out_path, rec)
        if n % 20 == 0:
            print(f"{n}/{len(sample)}  {crawl.bytes/1e6:.0f} MB  HMRC calls {verifier.calls}")

    rows = read_jsonl(out_path)
    by = defaultdict(Counter)
    for r in rows:
        by[r["stratum"]][r["state"]] += 1
        by["ALL"][r["state"]] += 1
    metrics = {}
    for s, c in by.items():
        n = sum(c.values())
        found = c["FOUND_A"] + c["FOUND_B"]
        metrics[s] = {"n": n, **dict(c), "found": found, "coverage": found / n,
                      "coverage_wilson95": stats.wilson(found, n)}
    (RESULTS / f"forward_{a.source}_metrics.json").write_text(json.dumps(metrics, indent=2))
    with (RESULTS / f"forward_{a.source}.csv").open("w", newline="", encoding="utf-8") as f:
        cols = ["crn", "name", "stratum", "sic", "incorporated", "host", "site", "state", "vrn", "tier"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
