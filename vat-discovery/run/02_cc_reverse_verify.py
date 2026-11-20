from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from common import DATA, RESULTS, ROOT, find_ch_zip, read_jsonl
from vatdisc import attribute, ch, hmrc, stats, vies


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", default=str(DATA / "cc_hosts.jsonl"),
                    help="harvest file; evidence/pilot/cc_hosts_pilot.jsonl replays the pilot's 60 blocks")
    ap.add_argument("--xi", action="store_true", help="also ask VIES (XI prefix) about numbers HMRC did not answer")
    ap.add_argument("--replay-pilot", action="store_true",
                    help="no network at all: recompute the pilot tables from evidence/pilot/ (harvest, HMRC and "
                         "VIES answers, Companies House look-ups)")
    a = ap.parse_args()
    pilot = ROOT / "evidence" / "pilot"
    if a.replay_pilot:
        a.hosts = str(pilot / "cc_hosts_pilot.jsonl")
    rows = read_jsonl(Path(a.hosts))
    frame = [r for r in rows if r["type"] == "frame"][-1]
    block_rows = {r["block"]: r for r in rows if r["type"] == "block_done"}
    done_blocks = set(block_rows)
    hosts = [r for r in rows if r["type"] == "host" and r["block"] in done_blocks]
    cand = [h for h in hosts if h["vat"]]
    vrns = sorted({v for h in cand for v in h["vat"]})
    n_hosts = sum(b["hosts"] for b in block_rows.values())
    n_pages = sum(b.get("with_pages", 0) for b in block_rows.values())
    print(f"{len(done_blocks)} blocks, {n_hosts:,} hosts, {len(cand)} hosts with candidates, {len(vrns)} distinct numbers")

    cache_file = DATA / "hmrc_cache.jsonl"
    xi_file = DATA / "vies_xi_cache.jsonl"
    for target, seed in ((cache_file, pilot / "hmrc_checked.jsonl"), (xi_file, pilot / "vies_xi_checked.jsonl")):
        if not target.exists() and seed.exists():
            shutil.copy(seed, target)
    cache, xi_cache = hmrc.Cache(cache_file), hmrc.Cache(xi_file)
    checks = {}
    if a.replay_pilot:
        checks = {v: cache.get(v) or hmrc.Check(v, None) for v in vrns}
        backend, calls, refused = "replay", 0, 0
    else:
        verifier = hmrc.default_verifier(cache)
        print(f"verifying with HMRC via {verifier.backend} ...")
        for i, v in enumerate(vrns, 1):
            checks[v] = verifier.check(v)
            if i % 25 == 0:
                print(f"  {i}/{len(vrns)}  (calls {verifier.calls}, 429s {verifier.rate_limited})")
        backend, calls, refused = verifier.backend, verifier.calls, verifier.rate_limited
    for v, c in list(checks.items()):
        if c.valid is None:
            x = xi_cache.get(v) or (vies.check_xi(v) if a.xi and not a.replay_pilot else None)
            if x is not None:
                xi_cache.put(x) if v not in xi_cache.mem else None
                if x.valid:
                    checks[v] = x

    live = {v: c for v, c in checks.items() if c.valid}
    if a.replay_pilot:
        comps = []
        for line in (pilot / "ch_lookup.psv").read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "|MISSING|" in line or not line.strip():
                continue
            crn, name, status, pc, prev = (line.split("|") + [""] * 5)[:5]
            comps.append(ch.Company(crn=crn, name=name, status=status, postcode=pc,
                                    previous=tuple(p.strip() for p in prev.split(";") if p.strip())))
        idx = ch.NameIndex.from_companies(comps)
    else:
        print("loading the Companies House register for the join ...")
        idx = ch.NameIndex(find_ch_zip(), wanted={c.name for c in live.values()},
                           wanted_crns={c for h in cand for c in h["crn"]})

    out_rows, per_block = [], defaultdict(lambda: Counter())
    for h in cand:
        for v in h["vat"]:
            c = checks[v]
            page_crns = [x for x in h["crn"] if x in idx.by_crn]
            def agrees(co) -> bool:
                return any(attribute.names.grade(c.name, n) in ("EXACT", "NORMALISED", "FUZZY")
                           for n in (co.name, *co.previous))
            w1 = next((idx.by_crn[x] for x in page_crns if c.valid and agrees(idx.by_crn[x])), None)
            w1_state = "none" if not page_crns else ("agree" if w1 else "disagree")
            reg, n_reg = attribute.pick_register_match(idx.resolve(c.name), c.address) if c.valid else (None, 0)
            target = w1 or reg or (idx.by_crn[page_crns[0]] if page_crns else None)
            verdict = attribute.judge(c.valid, c.name, c.address, target.name if target else None,
                                      target.postcode if target else None, page_has_crn=bool(w1),
                                      ch_previous_names=target.previous if target else (),
                                      register_matches=max(1, n_reg))
            out_rows.append({"host": h["host"], "block": h["block"], "vrn": v, "evidence": "+".join(h["vat"][v]),
                             "verified_by": c.backend if c.valid is not None else "",
                             "hmrc_valid": c.valid, "hmrc_name": c.name, "page_crns": " ".join(h["crn"]),
                             "page_witness": w1_state if c.valid else "",
                             "crn": target.crn if target else "", "ch_name": target.name if target else "",
                             "tier": verdict.tier, "name_grade": verdict.name_grade,
                             "postcode_match": verdict.postcode_match, "reason": verdict.reason})
            per_block[h["block"]][verdict.tier] += 1

    with (RESULTS / "cc_pairs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)

    tiers = Counter(r["tier"] for r in out_rows)
    B = frame["population_blocks"]
    blocks = sorted(done_blocks)
    est = lambda sel: stats.cluster_total([sum(per_block[b][t] for t in sel) for b in blocks], B)
    two_witness = [r for r in out_rows if r["page_witness"] in ("agree", "disagree")]
    disagree = [r for r in two_witness if r["page_witness"] == "disagree"]
    m = {
        "crawl": frame["crawl"], "blocks_sampled": len(blocks), "blocks_population": B,
        "hosts_sampled": n_hosts, "hosts_with_pages": n_pages,
        "hosts_with_candidate": len(cand), "distinct_candidates": len(vrns),
        "hmrc_live": len(live), "hmrc_not_found": sum(1 for c in checks.values() if c.valid is False),
        "hmrc_no_answer": sum(1 for c in checks.values() if c.valid is None),
        "note": "pairs with hmrc_valid = None were NOT verified and are not counted anywhere below",
        "tiers": dict(tiers),
        "distinct_companies_A_B": len({r["crn"] for r in out_rows if r["tier"] in "AB"}),
        "two_witness_pairs": len(two_witness), "two_witness_disagreements": len(disagree),
        "disagreement_rate_wilson95": stats.wilson(len(disagree), len(two_witness)),
        "extrapolated_host_pairs_tier_A": est("A"), "extrapolated_host_pairs_tier_A_B": est("AB"),
        "verified_by": dict(Counter(c.backend for c in checks.values() if c.valid is not None)),
        "verifier": backend, "hmrc_calls": calls, "hmrc_429": refused,
    }
    (RESULTS / "cc_metrics.json").write_text(json.dumps(m, indent=2))
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
