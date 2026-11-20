"""Pull identifier candidates out of a web page.

Three things are extracted from the visible text:

- VAT number candidates, each tagged with the evidence that produced it
    - "vatword"  : the word VAT within 40 non-digit characters before 9 digits
    - "gbprefix" : "GB" immediately followed by 9 digits
    - "eori"     : "GB" + 9 digits + "000"  (a GB EORI is the VRN + 000)
    - "jsonld"   : schema.org "vatID" / "taxID" in the raw HTML
  Nothing is kept unless it passes the VAT checksum ("vat.scheme"), which
  on its own rejects ~98% of random 9-digit strings (phone numbers, prices).
- Companies House number (CRN) candidates: 6-8 digits (or SC/NI/OC + 6) after
  a company/registration keyword.
- A flag for explicit statements such as "we are not VAT registered".
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from . import vat

_NINE = r"((?:\d[ .\-]?){8}\d)(?![ .\-]?\d)"
RE_VATWORD = re.compile(r"\bV\.?A\.?T\b[^\d]{0,40}?(?:GB|UK)?\s*" + _NINE, re.I)
RE_GBPREFIX = re.compile(r"\bGB ?" + _NINE)
RE_EORI = re.compile(r"\b(?:GB|XI) ?(\d{9}) ?000\b")
RE_JSONLD = re.compile(r'"(?:vatID|taxID)"\s*:\s*"([^"]{5,30})"', re.I)
RE_CRN = re.compile(
    r"\b(?:compan(?:y|ies)|co\.?|registration|registered|reg\.?|crn)\b[^\d]{0,45}?"
    r"(?<![A-Za-z0-9])((?:SC|NI|OC|SO|NC) ?\d{6}|\d{8}|\d{7}|\d{6})(?!\d)",
    re.I,
)
RE_NEGATIVE = re.compile(r"\bnot (?:currently )?(?:VAT[- ]registered|registered for VAT)\b", re.I)
_SKIP = {"script", "style", "noscript", "svg", "template"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title.append(data)
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Return (visible_text, title) with whitespace collapsed."""
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:
        crude = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
        return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", crude))), ""
    text = re.sub(r"[ \s]+", " ", " ".join(p.parts))
    return text, re.sub(r"\s+", " ", "".join(p.title)).strip()[:120]


@dataclass
class Extraction:
    vat: dict[str, set[str]] = field(default_factory=dict)
    crn: dict[str, int] = field(default_factory=dict)
    negative: bool = False
    title: str = ""
    text_len: int = 0

    def merge(self, other: "Extraction") -> None:
        for v, tags in other.vat.items():
            self.vat.setdefault(v, set()).update(tags)
        for c, n in other.crn.items():
            self.crn[c] = self.crn.get(c, 0) + n
        self.negative = self.negative or other.negative
        self.title = self.title or other.title
        self.text_len += other.text_len


def normalise_crn(raw: str) -> str:
    c = re.sub(r"\s", "", raw).upper()
    return c.zfill(8) if c.isdigit() else c


def extract_text(text: str) -> Extraction:
    out = Extraction(text_len=len(text))

    def add(raw: str, tag: str) -> None:
        v = re.sub(r"\D", "", raw)
        if vat.scheme(v):
            out.vat.setdefault(v, set()).add(tag)

    for m in RE_VATWORD.finditer(text):
        add(m.group(1), "vatword")
    for m in RE_GBPREFIX.finditer(text):
        add(m.group(1), "gbprefix")
    for m in RE_EORI.finditer(text):
        add(m.group(1), "eori")
    for m in RE_CRN.finditer(text):
        if re.search(r"V\.?A\.?T", m.group(0), re.I):
            continue
        c = normalise_crn(m.group(1))
        out.crn[c] = out.crn.get(c, 0) + 1
    out.negative = bool(RE_NEGATIVE.search(text))
    return out


def extract_html(html: str) -> Extraction:
    text, title = html_to_text(html)
    out = extract_text(text)
    out.title = title
    for m in RE_JSONLD.finditer(html):
        digits = re.sub(r"\D", "", m.group(1))[:9]
        if vat.scheme(digits):
            out.vat.setdefault(digits, set()).add("jsonld")
    return out
