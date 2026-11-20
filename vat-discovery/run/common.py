from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA, RESULTS = ROOT / "data", ROOT / "results"
DATA.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)

from vatdisc import vat


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def append_jsonl(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def seeded_indices(n_population: int, k: int, seed: int) -> list[int]:
    """k distinct indices in [0, n_population)."""
    gen, seen, out = vat._mulberry32(seed), set(), []
    while len(out) < min(k, n_population):
        i = int(next(gen) * n_population)
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def find_ch_zip() -> Path:
    hits = sorted(DATA.glob("BasicCompanyDataAsOneFile-*.zip"))
    if not hits:
        sys.exit("Companies House snapshot not found.\n"
                 "Download BasicCompanyDataAsOneFile-YYYY-MM-01.zip (~470 MB) from\n"
                 "  https://download.companieshouse.gov.uk/en_output.html\n"
                 f"and put it in {DATA}")
    return hits[-1]
