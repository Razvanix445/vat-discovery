"""A GB EORI number is 'GB' + VAT number + '000'.

HMRC's "Check an EORI number" API takes up to 10 EORIs per call and returns,
for traders who agreed to be listed, the trader name and address.
"""
from __future__ import annotations

import json

import requests

from common import DATA, RESULTS, read_jsonl
from vatdisc import names

URL = "https://api.service.hmrc.gov.uk/customs/eori/lookup/check-multiple-eori"


def main() -> None:
    live = [r for r in read_jsonl(DATA / "hmrc_cache.jsonl") if r.get("valid")][:200]
    out, s = [], requests.Session()
    for i in range(0, len(live), 10):
        batch = live[i:i + 10]
        r = s.post(URL, json={"eoris": [f"GB{c['vrn']}000" for c in batch]}, timeout=30,
                   headers={"Accept": "application/vnd.hmrc.1.0+json"})
        if r.status_code != 200:
            print(f"HTTP {r.status_code}: {r.text[:200]!r} -- stopping, not retrying")
            break
        by = {e["eori"]: e for e in r.json()}
        for c in batch:
            e = by.get(f"GB{c['vrn']}000", {})
            out.append({"vrn": c["vrn"], "vat_name": c["name"], "eori_valid": e.get("valid"),
                        "eori_name": e.get("companyDetails", {}).get("traderName", ""),
                        "agree": names.grade(c["name"], e.get("companyDetails", {}).get("traderName", ""))})
    n = len(out)
    summary = {"checked": n, "eori_valid": sum(1 for o in out if o["eori_valid"]),
               "name_published": sum(1 for o in out if o["eori_name"]),
               "name_agrees": sum(1 for o in out if o["agree"] in ("EXACT", "NORMALISED"))}
    (RESULTS / "eori_probe.json").write_text(json.dumps({"summary": summary, "rows": out}, indent=2))
    print(summary)


if __name__ == "__main__":
    main()
