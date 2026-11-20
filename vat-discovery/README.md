# VAT Identifier Discovery

I think that only a small part of a UK company VAT dataset can be built from the open web. Few companies publish their VAT number online and HMRC no
longer lets you verify numbers in bulk without approved access. What the web gives you is a small set
of numbers you can trust. The rest of what this customer needs is on the invoices their suppliers
already sent them.

Every number below comes from a run recorded in `evidence/LOG.md` (entries P01–P16). The raw
data is in `evidence/pilot/`.

## Summary

| | Result |
|---|---|
| `.co.uk` sites that show a valid VAT number | 116 of 4,988 sampled (2.3%) |
| Random active companies where I found a verified number | 0 of 400 |
| Harvested numbers I could verify | 8 of 112. All 8 live and attributed to a company |
| Same harvest on `.de` sites | 199 of 2,423 (8.2%) |
| Random companies with a VAT number on OpenCorporates | 35 of 153 (23%) |

---

## Part 1: Research

### The problem has three parts

1. Find a number that could belong to the company.
2. Prove it belongs to *this* company. HMRC saying "valid" only proves the number exists. A web
   agency's VAT number in a client's footer is valid and wrong.
3. When nothing is found, tell "not registered" apart from "I missed it".

For scale: HMRC has about 2.18M VAT registrations, 1.77M of them companies. Against ~4.2M
live companies, a random company has about a 40% chance of being registered. About 10% of
registrations change every year.

### The verifier (P01, P02, P08, P14)

I expected a free API, because most guides still describe one. It no longer exists.

- API v1 was removed in February 2025 (now returns 404). v2 needs OAuth credentials that take about
  two weeks to get, and HMRC says it is only for due diligence on trading partners.
- The public web form needs no account. It answered about 55 lookups, then started returning 429 and
  after that allowed only a few per hour. I stopped there.
- HMRC sometimes returns names with spaces inside words (`(GR OUP) LIMITE D`). Exact name matching
  breaks on this, so the matcher also compares names with all spaces removed.

This decided the shape of Part 2: harvesting was cheap, verification was the bottleneck.

### Websites, through Common Crawl (P06, P07)

UK law requires a company website to show the company number, and a VAT-registered business to show
its VAT number. A page with both gives you an exact join to Companies House, with no name matching.

Instead of crawling sites one by one I used Common Crawl. Its index is sorted by reversed domain, so
all of `.co.uk` sits in one range: 14,753 index blocks. I sampled 60 blocks at random and read the
home page plus one legal-looking page (terms, privacy, contact) for each site.

| | Sites |
|---|---|
| Sampled | 4,988 |
| With a readable page | 3,786 |
| Show a company number | 410 |
| Show a checksum-valid VAT number | 116 |
| Show both | 93 |

Most sites that show a company number don't show a VAT number. I re-read the 317 sites with a
company number but no VAT number, using up to six extra pages each, and found one more number. So
reading more pages isn't the fix; the numbers just aren't there.

Common Crawl also throttles hard. Six parallel requests got me blocked within minutes; two parallel
requests with a short pause ran fine.

### Other sources

- **EORI** (P07, P09). A GB EORI is `GB` + VAT number + `000`. No EORI appeared in 5,186 pages. On
  HMRC's EORI checker, 7 of the 9 confirmed VAT numbers gave a live EORI, but only 1 showed a name.
  So the link exists, but it doesn't help with discovery or naming.
- **Peppol directory** (P05, P10). This source wasn't in the brief. It lists 23,206 UK e-invoicing
  participants, and most use scheme `9932`, which is the GB VAT number. Of the first 40 I checked, 38
  were live but 9 of those weren't companies. The names copy HMRC's spacing errors, so the entries
  were made from an HMRC lookup. Accurate, but small (~1% of the target) and not an independent
  check.
- **VIES with the XI prefix** (P15). VIES still validates UK numbers under the Northern Ireland
  prefix and returns name and address (`XI220430231` → TESCO PLC). It confirmed 3 of my 113
  candidates. "Invalid" means nothing, because only NI-registered traders are in it, but "valid" is a
  free second check.
- **Filed accounts** (P04). Companies House publishes accounts in bulk, tagged and keyed by company
  number. In 8,589 filings, none had a VAT number, either tagged or in the text. About 5.6% mention
  VAT as a line item, which is useful evidence that a company *is* registered (part 3 of the
  problem).
- **Procurement, Find a Tender** (P03). There were 3,801 parties, identified by PPON, company number,
  charity or NHS codes. None had a VAT number.
- **OpenCorporates** (P11, P13). They already have this data. Their documentation describes
  generating every checksum-valid number, checking each with HMRC, and keeping exact name matches.
  On my random sample, 35 of 153 companies (23%) have a "GB VAT Number" row. That's the benchmark the
  web route has to beat, and it doesn't on coverage.
- Not tested: Gazette insolvency notices and council spend files. I expect them to behave like
  procurement data (keyed by company number, no VAT number), but I didn't check.

### Dead ends

| Source | Expected | Why it failed |
|---|---|---|
| HMRC API v1 | Free bulk verification | Removed, 404 |
| HMRC API v2 | Same, with a key | Needs approved credentials (~2 weeks) |
| HMRC web form | Slow verifier | 429 after ~55 lookups, a few per hour after that |
| Accounts iXBRL | VAT number tagged per company | 0 of 8,589 filings |
| Find a Tender | VAT as a supplier ID | 0 of 3,801 parties |
| EORI on websites | Second pattern for the same number | 0 in 5,186 pages |
| More pages per site | Numbers hidden in T&Cs | 1 extra number from 469 pages |
| Guessing domains from company names | A site for most companies | 45 of 400 found, 12 tied to the company, 0 verified numbers |

---

## Part 2: Proof of concept

### How it works

Common Crawl sample -> read 2 pages per site -> candidates that pass the checksum
   -> HMRC (or VIES XI): is it live, and whose is it?
   -> W1: company number on the same page;
     W2: HMRC's name == Companies House name
   -> A: both agree;   B: W2 only, unique;   C: needs review;   X: disagree, rejected

A number is never attached to a company just because the page shows it. HMRC's registered name has
to match the Companies House name. The company number on the page is a second, independent check.
For example, one sampled site was a parked domain showing the hosting company's details. The pair it
produced was correct, but for the hosting company, not the domain owner.

### Two samples

**Sample A: websites.** 60 random index blocks out of 14,753, using every site that starts in those
blocks: 4,988 sites. It's representative of `.co.uk` as Common Crawl sees it. It doesn't cover `.com`
or sites Common Crawl didn't crawl, and most of the sites aren't company sites.

**Sample B: companies.** This is the sample that answers the coverage question. I drew company
numbers uniformly from 1 to 17,600,000, looked each up at Companies House, and kept the active ones
until I had 400 (1,625 draws). A company's web presence plays no part in whether it's picked, and the
sample looks like the real register: 155 of the 400 were incorporated in 2024–26, and 106 haven't
filed accounts yet. Scottish (`SC`) and Northern Irish (`NI`) numbers aren't in this frame.

### Results, Sample A

Of the 112 distinct candidate numbers, 8 could be verified before HMRC stopped answering: 5 through
the HMRC form and 3 through VIES XI. All 8 are live, and all 8 belong to a company.

| Site | VAT no. | Name returned | Company | Tier |
|---|---|---|---|---|
| lusona.co.uk | 125474027 | LUSONA CONSULTANCY (GROUP) LIMITED | SC419051 | A |
| ela8.co.uk | 904158931 | ELA8 LIMITED | 06060813 | A |
| lussocampers.co.uk | 420619718 | LUSSO CAMPERS LIMITED | 14099533 | A |
| floorstoreonline.co.uk | 411307940 | JIMS CARPETS LTD | 01220080 | A |
| floortexeurope.co.uk | 790890684 | FLOORTEX EUROPE LTD | 04338164 | A |
| sanofi.co.uk (+ sanofivaccines) | 246079843 | AVENTIS PHARMA LIMITED | 01535640 | A |
| ekotec.co.uk | 817824609 | EKOTEC LIMITED | 04767608 | B |
| valueroofingsupplies.co.uk | 334592786 | ALLTYPE ROOFING SUPPLIES (GR OUP) LIMITE D | 12173820 | B |

Three of these would have gone wrong with a simpler approach:

- Sanofi: the brand is Sanofi, but the legal entity is Aventis Pharma Limited.
- Ekotec: the register has an active EKOTEC LIMITED and a dissolved EKOTEC LTD. Status and postcode
  pick the right one.
- Alltype: exact name matching fails because of HMRC's spacing.

The other 104 numbers are unverified and not counted. Scaled to the whole crawl, 116 sites per 60
blocks is about 28,500 sites (95% CI 22,500–34,600), so under 1.6% of VAT-registered companies even
if every number verified.

### False positives

A false positive here means a live number attached to the wrong company. On the 6 pairs where both
checks applied, they disagreed 0 times. Six is too few to claim much: the 95% upper bound is 39%.
With all ~93 two-witness sites verified, zero disagreements would bound the rate at about 4%. The
script reports this automatically, and rejected pairs are kept with the reason.

### Results, Sample B

| 400 random active companies | n |
|---|---|
| No guessed domain exists in the crawl | 355 |
| Domain exists, nothing ties it to the company | 33 |
| Site names the company, no VAT number | 11 |
| Site shows the company number and a VAT number | 1 |
| ...that HMRC confirms | 0 |

The one hit is the most useful row. hbclogistics.co.uk shows the correct company number and a VAT
number that passes the checksum, but HMRC says the number isn't registered. A pipeline that trusted
"valid number on the company's own site" would have shipped it.

### What these numbers don't capture

- Only 8 of 112 numbers verified, so every rate based on them has a wide interval.
- Only `.co.uk` was harvested, with two pages per site. JavaScript-rendered footers and PDFs are
  invisible.
- VAT groups: one number covers several companies, but HMRC returns only the lead member. The
  others get rejected, which is the safe side to fail on.
- Trading names and renames can make tier B miss. Previous names from Companies House recover some.
- I don't know which of the 400 companies are VAT registered. The prior is ~40%.

---

## Part 3: With real resources

1. **Get approved HMRC API access.** Nothing works without it. At 3 requests/second, one app checks
   about 259k numbers a day, enough to re-verify all ~1.8M registered companies weekly.
2. **Use the customer's own invoices.** Every VAT invoice must show the supplier's VAT number, and
   they pay 40,000 suppliers monthly. Extract name + VAT number from one invoice per supplier, verify
   with HMRC, and match with the same two checks. It's not "open web", but it solves their problem.
3. **Run the web harvest on everything,** not a sample: `.uk`, UK `.com` sites, several crawls a
   year, PDFs and rendered pages.
4. **Use bought data as a benchmark,** not as a source.

### Cost per company (estimates)

| Route | Coverage | Cost |
|---|---|---|
| Common Crawl, `.co.uk`, one crawl | < 1.6% | A few tens of dollars on AWS, about $0.002 per verified company |
| + more TLDs, crawls, PDFs, rendering | maybe 2–4× that | Low thousands per year |
| Own crawl of ~10M `.uk` domains | ~10% at best | $1–3k per pass plain, $15–30k with rendering and proxies |
| Search API to find each company's site | adds little | $13–21k per pass for 4.2M companies |
| Customer invoices | ~100% of their VAT-registered suppliers | $400–2,000 per customer (~$0.03 per supplier) |
| Manual audit | — | 300 pairs/month, ~10 hours |

The web route is almost free and tops out in single digits. The invoice route costs much more per
company but covers what the customer actually needs.

### What breaks first

1. Verifier access. It already broke for me.
2. Staleness. At ~10% churn a year, a one-time verification is about 5% wrong after six months.
3. Name matching in the long tail: trading names, VAT groups, HMRC spacing, renames.
4. Common Crawl throttling if you run from outside AWS.
5. Bought feeds built by enumeration. They can't be refreshed now that the open API is gone.

### What I'd monitor

- The disagreement rate between the two checks, weekly, per source. This is the false-positive gauge.
- Drift on re-verification: the share of stored pairs whose HMRC answer changed. About 0.2% a week
  is expected from churn; a jump means a bug.
- One number on several companies outside known VAT groups, or one company with several numbers.
- HMRC 429 rate and the share of "no answer".
- Yield per source per crawl: candidates, live rate, tier mix.
- A fixed set of known-good and known-bad pairs run daily. Any change in their tier blocks a release.
- Agreement with the third of numbers the customer already holds. That's the only external reference.

---

## Debate topics

**Pointing the checksum at HMRC.** Seven free digits and two check digits under two schemes give
exactly 20M valid numbers. With ~2.3M live, about 1 in 9 is a hit. At 3 req/s that's 77 days and
you get the whole register. It works, and OpenCorporates did it. I didn't, not even on a small
sample, for four reasons. It's outside what HMRC says the service is for, and HMRC has since closed
the open API, so you couldn't keep it current. About a quarter of the results are sole traders, so
personal data. It only gives you name matching, with no second check. And it turns a shared public
service into a bulk export at everyone else's expense.

**Knowing it's wrong without ground truth.** Use two checks that fail for different reasons and
track how often they disagree. Add rules that need no reference: one number on several companies,
several numbers on one company. Watch how pairs drift on re-verification. Audit samples by hand:
zero errors in 300 bounds the error rate under 1%. The customer's existing third is a partial
reference. Capture–recapture between independent sources estimates what neither source has seen.

**Sources I wouldn't use in a product.** Anything built by enumerating HMRC, including bought feeds
made that way. The HMRC web form in production: its terms describe personal use and it's rate 
limited. Sole traders and partnerships, which are personal data and out of scope anyway.
OpenCorporates data without a commercial licence, since as I read it the licence is share-alike.
Marketplace seller pages, which are against platform terms and mostly individuals. The Peppol
directory, until its reuse terms are clear. I would use Common Crawl, Companies House data, and
HMRC answers from approved API access.

---

## Beyond the UK

**Germany: the same problem, but the hard part moves.** Discovery is easier. Every commercial site
needs an Impressum that includes the VAT ID, and competitors enforce it with legal warning letters.
Running the same harvest on `.de` found a VAT ID on 8.2% of sites, against 2.3% in the UK, and on 43%
of sites whose Impressum page was in the crawl. The new Wirtschafts-Identifikationsnummer is the VAT
ID plus `-00001`, so it's another way to find the same number.

Verification is harder. VIES confirmed 23 of 24 German numbers as valid but returned no name for any
of them. Germany's own service only confirms a name and address you supply, and only if you have a
German VAT ID yourself. So the check changes from "compare two registers" to "ask the tax office to
confirm my guess". The harvesting code survives the move with a new regex and checksum. Attribution
would have to be rebuilt around the Impressum, which has the name, address and HRB number in the
same block.

**For market priority,** ask three questions per country. Can the VAT number be derived from the
register number? Is the register free in bulk? Does the verifier return a name? Three yeses
(Belgium, Denmark) means the data is cheap to build and worth little on its own. The value is in
countries with a "no".

---

## Running it

```bash
pip install -r requirements.txt
pytest -q                                          # offline tests

python run/02_cc_reverse_verify.py --replay-pilot  # recompute Part 2 from evidence/
python run/01_cc_reverse_harvest.py --blocks 60    # harvest the same 60 blocks
python run/02_cc_reverse_verify.py                 # verify
python run/03_forward_sample.py --n 400            # Sample B
```

The experiments were run with a browser-console prototype (`probes/cc_toolkit.js`). `vatdisc/` is
the Python version of it, with the same sampling and extraction. HMRC checks use the API if
`HMRC_CLIENT_ID` / `HMRC_CLIENT_SECRET` are set, and otherwise use the public form slowly. Answers
are cached in `data/`, so runs can be resumed.
