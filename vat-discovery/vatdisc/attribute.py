"""Attribution: does this (verified) VAT number belong to this company?

The claim we sell is "VRN X belongs to company C". Two independent witnesses can back
that claim:

  W1  the PAGE     : a page that shows VRN X also shows company number C
  W2  the REGISTER : HMRC's registered name for X equals Companies House's
                     registered name for C (and same postcode)

Tiers
  A  W1 + W2 (name EXACT/NORMALISED)                      publish
  B  W2 only, name EXACT/NORMALISED, unique on register   publish, lower tier
  C  W2 FUZZY but postcode matches                        hold for review
  X  HMRC valid but names disagree                        reject (kept as audit trail)
  -  HMRC says not registered                             reject
  ?  HMRC has not answered                                not verified, counts for nothing
"""
from __future__ import annotations

from dataclasses import dataclass

from . import names


@dataclass
class Verdict:
    tier: str
    name_grade: str
    postcode_match: bool
    reason: str


def judge(hmrc_valid: bool | None, hmrc_name: str, hmrc_addr: str,
          ch_name: str | None, ch_postcode: str | None,
          page_has_crn: bool, ch_previous_names: tuple[str, ...] = (),
          register_matches: int = 1) -> Verdict:
    if hmrc_valid is None:
        return Verdict("?", "", False, "not verified: no answer from HMRC yet")
    if not hmrc_valid:
        return Verdict("-", "", False, "HMRC: not a live registration")
    if not ch_name:
        return Verdict("X", "", False, "no Companies House record to compare with")
    g = names.grade(hmrc_name, ch_name)
    if g == "MISMATCH":
        for prev in ch_previous_names:
            if names.grade(hmrc_name, prev) in ("EXACT", "NORMALISED"):
                g = "NORMALISED"
                break
    pc = names.same_postcode(hmrc_addr, ch_postcode)
    strong = g in ("EXACT", "NORMALISED")
    if strong and page_has_crn:
        return Verdict("A", g, pc, "page shows VRN+CRN and HMRC name = register name")
    if strong and register_matches == 1:
        return Verdict("B", g, pc, "HMRC name = a unique register name")
    if strong:
        return Verdict("C", g, pc, f"HMRC name matches {register_matches} register entries")
    if g == "FUZZY" and pc:
        return Verdict("C", g, pc, "near-identical name and same postcode")
    return Verdict("X", g, pc, "HMRC name and register name disagree")


def pick_register_match(candidates: list, hmrc_addr: str):
    """Several register entries can share one canonical name ("EKOTEC LIMITED",
    active, and "EKOTEC LTD", dissolved 2022).
    We will do the live companies first, then the one at HMRC's postcode.
    Returns (company or None, how many remained plausible).
    """
    if not candidates:
        return None, 0
    live = [c for c in candidates if getattr(c, "status", "").lower() == "active"] or list(candidates)
    if len(live) > 1:
        here = [c for c in live if names.same_postcode(hmrc_addr, getattr(c, "postcode", ""))]
        if len(here) == 1:
            live = here
    return live[0], len(live)
