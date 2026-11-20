from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import date

from common import DATA, RESULTS, append_jsonl, read_jsonl
from vatdisc import hmrc, names, peppol, stats, vat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2018-01-01")
    ap.add_argument("--verify", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    raw = DATA / "peppol_gb.jsonl"
    if not raw.exists():
        n = 0
        for p in peppol.harvest_gb(date.fromisoformat(a.start), date.today()):
            append_jsonl(raw, p.__dict__)
            n += 1
            if n % 1000 == 0:
                print(f"  harvested {n:,} (at {p.regdate})")
    parts = read_jsonl(raw)
    schemes = Counter(p["scheme"] for p in parts)
    vat_parts = [p for p in parts if p["scheme"] == "9932"]
    for p in vat_parts:
        p["vrn"] = vat.normalise(p["value"]) or ""
    good = [p for p in vat_parts if p["vrn"] and vat.is_valid(p["vrn"])]
    print(f"{len(parts):,} GB participants; schemes {dict(schemes.most_common(6))}; "
          f"{len(vat_parts):,} use 9932, {len(good):,} pass the checksum")

    random.Random(a.seed).shuffle(good)
    verifier = hmrc.default_verifier(hmrc.Cache(DATA / "hmrc_cache.jsonl"))
    out = DATA / "peppol_verified.jsonl"
    done = {r["vrn"] for r in read_jsonl(out)}
    for i, p in enumerate(good[: a.verify], 1):
        if p["vrn"] in done:
            continue
        c = verifier.check(p["vrn"])
        append_jsonl(out, dict(p, hmrc_valid=c.valid, hmrc_name=c.name, hmrc_address=c.address,
                               name_grade=names.grade(p["name"], c.name) if c.valid else ""))
        if i % 25 == 0:
            print(f"  verified {i}/{a.verify}")

    ver = read_jsonl(out)
    live = [r for r in ver if r["hmrc_valid"]]
    grades = Counter(r["name_grade"] for r in live)
    m = {"gb_participants": len(parts), "schemes": dict(schemes), "scheme_9932": len(vat_parts),
         "checksum_ok": len(good), "verified_sample": len(ver), "hmrc_live": len(live),
         "hmrc_live_wilson95": stats.wilson(len(live), len(ver)), "name_grades_among_live": dict(grades)}
    (RESULTS / "peppol_metrics.json").write_text(json.dumps(m, indent=2))
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
