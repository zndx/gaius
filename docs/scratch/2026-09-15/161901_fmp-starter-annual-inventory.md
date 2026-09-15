# FMP Starter Annual inventory (2026-09-15)

Plan from the dashboard: **Starter Annual**. Usage today: **0/300 calls per
minute**, **528 MB / 20 GB** trailing 30 days (~2.6% of bandwidth). Official
card: 300 calls/min, 5 years of history, **US coverage**, annual fundamentals
and ratios, EOD prices, profile/reference, market news, crypto and forex.
Bandwidth cap 20 GB / 30 days. Source: [pricing](https://site.financialmodelingprep.com/developer/docs/pricing)
and [playground](https://site.financialmodelingprep.com/playground).

Gaius `FMPClientConfig` still says **10,000 calls/day** and throttles to
**30/min** (10% of Starter). The live plan has no 10k/day cap on the
dashboard; the limiter is leaving ~90% of the minute budget on the floor.

Legend for Starter vs higher tiers (compare table):

| Mark | Meaning |
|------|---------|
| **US** | Starter: US exchanges, 5y history, annual statements |
| **P** | Premium: UK+CA, 30y, quarterly/TTM, 5-min+ charts, technicals |
| **U** | Ultimate: global, transcripts, 13F, ETF holdings, bulk, 1-min |

---

## 1. What the playground lists (stable API)

Every group below is on the API Viewer. **Starter can call the US/annual
subset**; Ultimate-only groups will 402.

### Company search
Stock symbol search, company name search, CIK, CUSIP, ISIN, stock screener,
exchange variants.

### Stock directory
Company symbols list, financial-statement symbols list, CIK list, symbol
changes, ETF list, actively trading list, earnings-transcript list,
available exchanges / sectors / industries / countries.

### Company information
Profile (symbol and CIK), company notes, stock peers, delisted companies,
employee count + historical, market cap + batch + historical, share float +
all-shares-float, latest/search M&A, executives, executive compensation +
benchmark.

### Quote
Stock quote / short, aftermarket trade/quote, price change, batch quotes,
exchange quotes, mutual fund / ETF / commodity / crypto / forex / index
quotes.

### Financial statements
Income / balance / cash flow (annual on Starter; TTM and as-reported more
on Premium), latest statements, key metrics, ratios, scores, owner
earnings, enterprise values, statement growth, 10-K JSON/XLSX, revenue
product and geographic segments.

### Charts
Light/full EOD, unadjusted, dividend-adjusted. **5-min and coarser
intraday on Starter**; 1-min is Ultimate.

### Economics
Treasury rates, economic indicators, economic calendar, market risk premium
(Premium+ for some).

### Analyst
Estimates, ratings snapshot + historical, price-target summary/consensus,
stock grades + historical + summary.

### Earnings, dividends, splits
Company dividends + calendar, earnings report + calendar, IPO calendar /
disclosure / prospectus, split details + calendar.

### Earnings transcripts — **Ultimate**
Latest transcripts, by symbol, dates, available symbols. Starter **402**.

### News
FMP articles, general news, press releases, stock / crypto / forex news,
search variants. (Press-releases-latest was **402** on this key in Aug.)

### Market calendar
Covered under earnings/dividends/splits/IPO above.

### Form 13F — **Ultimate**
Institutional ownership filings, extract, dates, holder analytics,
performance, industry breakdown. Starter **402**. Gaius still comments
this as "Premium only".

### Advanced / COT
Commitment of Traders report, analysis, list — Premium/Ultimate.

### Crypto / forex / commodity
Lists, quotes, historical light/full, interval charts (tier-limited).

### Insider & congressional
Latest insider, search by symbol/name, transaction types, statistics,
acquisition ownership. Senate/House latest + by name. Starter has **latest**
streams (used by `fmp_roll`).

### ESG — Premium/Ultimate
Search, ratings, benchmark.

### ETF & mutual funds — holdings **Ultimate**
Holdings, fund info, country allocation, asset exposure, sector weighting,
disclosures. Starter has ETF **quotes/list**, not holdings.

### Analyst ratings (TipRanks) — higher tiers
Separate from FMP grades.

### SEC filings
Latest 8-K, latest filings, by form type, by symbol, by CIK, by name,
company search, full profile, industry classification. **This is what
prospects_check uses (by symbol, recent 10-K/Q).**

### Indexes
Index list/quotes/charts, S&P 500 / Nasdaq / Dow constituents + historical.

### Discounted cash flow
DCF, levered DCF; custom DCF is Premium.

### Market hours
Global exchange hours, holidays.

### Market performance
Sector/industry performance + PE snapshots, gainers/losers/most active.

### Technical indicators — Premium
SMA, EMA, WMA, DEMA, TEMA, RSI, stdev, Williams, ADX.

### Fundraisers
Crowdfunding latest/search/by CIK, equity offering latest/search/by CIK.

### Bulk — **Ultimate**
Profile, ratings, DCF, scores, price targets, ETF holders, upgrades,
metrics TTM, ratios TTM, peers, earnings surprises, all three statements
(+ growth), EOD bulk.

---

## 2. What Gaius actually calls

`FMPEndpoint` names 16 kinds. The **check** uses one. **`fmp_roll`** uses
seven latest-streams. Update uses filings + profile.

| Call | Path (stable) | Used by | Starter |
|------|---------------|---------|---------|
| SEC filings by symbol | `/stable/sec-filings` | **prospects_check**, update | yes (US) |
| Company profile | `/stable/profile` | update | yes (US) |
| Stock news latest | `/stable/news/stock-latest` | fmp_roll | yes |
| General news | `/stable/news/general-latest` | fmp_roll | yes |
| FMP articles | `/stable/fmp-articles` | fmp_roll | yes |
| 8-K latest (7d) | `/stable/sec-filings-8k` | fmp_roll | yes |
| Insider latest | `/stable/insider-trading/latest` | fmp_roll | yes |
| M&A latest | `/stable/mergers-acquisitions-latest` | fmp_roll | yes |
| Senate/House latest | `/stable/senate-latest` `/house-latest` | fmp_roll | yes |
| Earnings calendar | `/stable/earnings-calendar` | client; roll filters | yes |
| Historical EOD | `/stable/historical-price-eod` | client helper | yes (5y) |
| Search name | `/stable/search-name` | client helper | yes |
| Employee count | `/stable/employee-count` | client helper | yes |
| Institutional holders | `/stable/institutional-ownership/…` | client, **402** | **Ultimate** |

Prospects **check** is: watchlist symbols → recent SEC filings → compare to
HX. That is **one endpoint**, a handful of tickers (MTN, CHTR, LLY in the
failed run). It never asks statements, ratios, quotes, calendars, news,
insiders, 8-K, employees, DCF, or screener.

`fmp_roll` is the only place that pulls the **landscape** streams, and it
compacts them into a RAM FIFO — not into prospect briefs or AgentRTC
context. Press-releases-latest, transcripts, latest-financials, 13F were
probed and 402'd (Aug 16 note).

---

## 3. Starvation vs the subscription

- **Minute budget:** 300/min paid; client uses 30/min. ~270 unused.
- **Bandwidth:** 528 MB of 20 GB (~3%). A daily US EOD + annual statements
  for a 20-name watchlist is tens of MB, not gigabytes.
- **Content left on the floor (Starter-legal, unused by check):**
  income/balance/cashflow, key metrics, ratios, scores, enterprise value,
  growth, DCF, quotes, 5-min charts, dividends/earnings/splits calendars,
  IPO calendar, peers, employees, float, M&A, insiders, 8-K, news,
  articles, sector performance, screener, executives.
- **Paid-for but not on Starter (do not build the check around these):**
  13F, earnings transcripts, ETF holdings, bulk dumps, 1-min bars,
  technicals, 30-year history, UK/CA.

The check was defined as "is there a new 10-K/Q on the watchlist?" Tests
and `RUNNER_TASK` then treated that as the whole FMP product. AgentRTC
therefore only ever hears that tiny delta (or a FIFO of latest-news
snippets from `fmp_roll`), not the evolving statement/calendar/ownership
landscape the key can already fetch.

Next: treat FMP as a **harvest membrane** (many Starter endpoints → HX),
and let Metaflow Complete thinking over that corpus — not a binary
filings-check that gates a second flow.
