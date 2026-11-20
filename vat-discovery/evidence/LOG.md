# Evidence log

The probes were run as
JavaScript `fetch` calls from a browser on a home connection. Raw data is in
`evidence/pilot/`.

## P01  HMRC API

    GET https://api.service.hmrc.gov.uk/organisations/vat/check-vat-number/lookup/220430231
      no Accept header                        -> 404 MATCHING_RESOURCE_NOT_FOUND
      Accept: application/vnd.hmrc.1.0+json   -> 404 MATCHING_RESOURCE_NOT_FOUND
      Accept: application/vnd.hmrc.2.0+json   -> 401 MISSING_CREDENTIALS

v1 was removed on 17 Feb 2025. v2 needs OAuth credentials. HMRC says registration takes around two
weeks and the API is for due diligence on VAT-registered businesses.

## P02  HMRC web form

    POST https://www.tax.service.gov.uk/check-vat-number/enter-vat-details   (csrfToken, target=<vrn>)
      220430231 -> /known    TESCO PLC, CIRRUS A, SHIRE PARK KESTREL WAY, WELWYN GARDEN CITY, AL7 1GA
      220430232 -> /unknown  VAT registration not found
      123456789 -> /unknown

No login, no CAPTCHA, no robots.txt.

## P03  Find a Tender (procurement)

    GET https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?limit=100   (17 pages, then 429)
    releases 1,700, parties 3,801
    identifier schemes: GB-PPON 1,999 | GB-COH 1,072 | none 624 | GB-NHS 55 | GB-CHC 22 | GB-MPR 16 | GB-UKPRN 13
    schemes containing VAT: 0
    885 mentions of "VAT" in the text, none followed by a 9-digit number

No VAT numbers. Useful only as a list of government suppliers, keyed by company number.

## P04  Companies House accounts (iXBRL bulk)

    one daily accounts file: 60.9 MiB, 8,589 filings, 476 MB of text
    filings with a company-number tag        8,573   (parser check)
    filings with a VATRegistrationNumber tag     0
    'VAT' near a checksum-valid 9-digit number   0
    filings mentioning VAT at all              483 (5.6%), e.g. "VAT 17,495 7,053", "Turnover is stated net of VAT"

No VAT numbers. A VAT line in the accounts is evidence that the company is registered, which helps
separate "not registered" from "not found".

## P05  Peppol directory

    GET https://directory.peppol.eu/search/1.0/json?country=GB&rpc=100&rpi=<n>
    total GB participants: 23,206
    first 1,000 by scheme: 9932 (GB VAT) 979 | 0208 7 | 9925 6 | 0088 3 | 9918 2 | other 3
    paging stops at 1,000 results (HTTP 400 on page 11)
    of the 979 '9932' IDs: 974 pass the VAT checksum, 5 are company numbers typed into the VAT field

## P06  Common Crawl, size of the UK slice

    crawl: CC-MAIN-2026-43 (October 2026)
    cluster.idx is 104.5 MB; binary search with HTTP Range finds the 'uk,' range (2.3 MB of index)
    .uk index blocks: 19,647 (~59M captures, 5.46 GB compressed)
      uk,co 14,753 | uk,org 1,948 | uk,ac 1,228 | uk,gov 533 | uk,sch 169 | uk,nhs 87 | other ~900
    one block: ~271 KB, fetched and parsed in ~0.5 s

## P07  Common Crawl harvest, .co.uk

Frame: the 14,753 `uk,co,` blocks. Sample: 60 blocks, seed 43 (`run/common.py:seeded_indices`
draws the same blocks). Unit: hosts whose first capture is in a sampled block. Per host: home page
and the shortest legal-looking URL.

    hosts sampled                           4,988
    hosts with a readable page              3,786   (the rest are redirects or errors only)
    pages read                              5,186
    hosts with a checksum-valid VAT number    116   (112 distinct numbers)
    hosts with a company number               410
    hosts with both                            93
    how the 116 were found: "VAT" keyword 109, "GB" prefix 34, schema.org vatID 7, EORI pattern 0
    explicit "not VAT registered"               1

Per block: `pilot/cc_block_counts.txt`. Candidates: `pilot/cc_candidates.psv`.

Throttling: 6 parallel requests got the client blocked (403 on everything, 35 of 60 blocks failed).
Access came back after a few minutes. 2 parallel requests with a short pause ran clean. The failed
blocks were re-run.

### P07b  More pages per host

For the 317 hosts with a company number but no VAT number, read up to 6 more legal-looking pages
(terms, privacy, contact, about, faq, delivery, returns, policy).

    hosts with no such pages in the crawl   132
    extra pages read                        469
    hosts where a VAT number appeared         1

## P08  HMRC web form under repeated use

    41 lookups, one every 10-15 s: all answered (median 241 ms)
    3 lookups with no pause: 2nd and 3rd -> HTTP 429 (empty body, no Retry-After)
    retries 60 s apart: all 429
    after a long pause: a couple of lookups answered, then 429 again
    later lookups: the form POST is accepted, the result page returns 429

I stopped at that point.

## P09  EORI

    POST https://api.service.hmrc.gov.uk/customs/eori/lookup/check-multiple-eori
      v1.0 -> 403 (empty body)    v2.0 -> 404

Checked by hand on the public EORI form, for the confirmed VAT numbers plus Tesco:

    GB220430231000  Tesco             valid, name not shared
    GB420619718000  Lusso Campers     not an EORI
    GB125474027000  Lusona            not an EORI
    GB904158931000  Ela8              valid, name not shared
    GB817824609000  Ekotec            valid, name not shared
    GB334592786000  Alltype Roofing   valid, ALLTYPE ROOFING SUPPLIES (GROUP) LIMITED, ROMFORD RM3 8RF
    GB246079843000  Aventis Pharma    valid, name not shared
    GB411307940000  Jims Carpets      valid, name not shared
    GB790890684000  Floortex Europe   valid, name not shared

GB + VAT + 000 is a live EORI for 7 of 9 and shows a name for 1. No EORI was printed on any of the
5,186 pages in P07. Only already-confirmed numbers were checked here.

## P10  Peppol entries against HMRC

The first 41 `9932:` participants for GB. This is not a random sample: 36 have the same
registration date. Data: `pilot/peppol_first41.psv`.

    company number in the VAT field (not checked)   1
    checked with HMRC                              40
    live                                           38
    directory name vs HMRC name: same 35, same after normalising 1, spacing only 1, different 1
    live but not a company                          9   (individuals, partnerships)

The directory copies HMRC's spacing errors ("LIM ITED", "MA INTENANCE L TD"), so the entries were
made from an HMRC lookup. Accurate, but not an independent source.

## P11  Existing providers

OpenCorporates knowledge base, "GB VAT Code": they generate every checksum-valid number, check each
with the GOV.UK VAT service, and keep a number only on a strict 1:1 company name match. They mention
going from about 900M to 18M checks. vat-search.co.uk and vat-search.eu advertise the same kind of
lookup.

## P12  Random companies -> website -> VAT number

Sample: company numbers uniform on 1..17,600,000 (just above the newest issued number), generator
`vat._mulberry32(11)`. Each was looked up on Companies House and kept if its status was "Active".
400 were kept after 1,625 draws. List: `pilot/forward_sample_crns.txt`.

    incorporated 2024-26: 155 | 2019-23: 105 | 2009-18: 82 | before 2009: 58
    no accounts filed yet: 106
    private limited by shares 380, by guarantee 17, CIC 3

Method: 2-3 domain guesses from the name x (.co.uk, .com, .uk), looked up in the CC index (2,254
lookups). Where a host exists, the home page and one legal page go through the same extractor.

    no guessed host in the crawl                  355
    host exists, nothing ties it to the company    33
    page shows the registered name                  8
    page shows the company's own number             4
    page shows a checksum-valid VAT number          1   hbclogistics.co.uk, company 10681180, VAT 270624318
    HMRC on 270624318                                   VAT registration not found

Verified numbers: 0 of 400. Data: `pilot/forward_sites.psv`.

## P13  OpenCorporates coverage on the same sample

robots.txt allows `/companies/`. One page per company, 3.5 s apart, in the random draw order. The
VAT number itself needs a login, but whether the row exists is visible.

    pages read                     153   (stopped after three 429s in a row)
    with a "GB VAT Number" row      35   (22.9%, 95% CI 17.0-30.1%)

## P14  HMRC verification of the harvested numbers

Order: `pilot/verify_order.txt` (seeded shuffle after the first 4). Answers:

    125474027  LUSONA CONSULTANCY (GROUP) LIMITED           ML4 3PR
    817824609  EKOTEC LIMITED                               ST16 1DA
    904158931  ELA8 LIMITED                                 OX1 4HL
    420619718  LUSSO CAMPERS LIMITED                        BD7 4JA
    334592786  ALLTYPE ROOFING SUPPLIES (GR OUP) LIMITE D   RM3 8RF
    270624318  (from P12)                                   VAT registration not found

After that, every lookup and every retry (5 min apart, plus re-reads of the result page) got a 429.
I stopped. The 429 always lands on the result page after the redirect. I didn't count the redirect
as an answer. Data: `pilot/hmrc_checked.jsonl`.

## P15  VIES

    GET https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{MS}/vat/{number}
    DE 136695977    INVALID   name ---
    ES A28015865    VALID     name ---
    BE 0404621642   VALID     NV NOKIA BELL, Copernicuslaan 50, 2018 Antwerpen
    DK 22756214     VALID     A.P. MØLLER - MÆRSK A/S, Esplanaden 50, 1263 København K
    XI 220430231    VALID     TESCO PLC, ... WELWYN GARDEN CITY AL7 1GA

All 113 candidates (112 harvested + 1 from P12) checked with the XI prefix, no errors:

    valid     3   246079843 AVENTIS PHARMA LIMITED (RG6 1PT), 411307940 JIMS CARPETS LTD (LS9 0AR),
                  790890684 FLOORTEX EUROPE LTD (GL20 8DN)
    invalid 110   meaningless for GB registrations: the 5 numbers HMRC confirmed are all XI-invalid

Data: `pilot/vies_xi_checked.jsonl`. Attribution of all 8 confirmed numbers
(`python run/02_cc_reverse_verify.py --replay-pilot`): `pilot/cc_pairs.csv`.

## P16  The same harvest on .de

Same crawl and method, prefix `de,` (38,117 blocks). 30 blocks drawn with seed 49; 27 finished. The
pattern is a USt/UID/VAT/MwSt keyword or a `DE` prefix, then 9 digits that pass the German check
digit. Pages read: the home page and the Impressum when the crawl has one.

    hosts sampled                     2,423
    with a readable page              1,922
    with a valid USt-IdNr               199   (8.2% of hosts, 192 distinct numbers)
    Impressum page in the crawl         343
      of those, with a USt-IdNr         147   (43%)
    with an HRA/HRB number               99   (68 also with a USt-IdNr)

VIES on the first 24 numbers: 23 valid, 1 invalid, no names returned. Per block:
`pilot/de_block_counts.txt`.

The German check digit passes 1 random string in 10 (the UK one passes 1 in 50), so the keyword does
more of the filtering here. 191 of the 199 hosts were found through the keyword.
