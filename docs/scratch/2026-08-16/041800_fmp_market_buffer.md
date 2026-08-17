# FMP market buffer (Starter-tier streams)

Watchlist stays the *primary* aperture (`[*]`). The RAM FIFO now also
ingests market-wide FMP rows that this key can actually fetch:

| Stream | Path | Starter |
|--------|------|---------|
| Stock news | `/stable/news/stock-latest` | yes |
| General news | `/stable/news/general-latest` | yes |
| FMP articles | `/stable/fmp-articles` | yes |
| 8-K (7d) | `/stable/sec-filings-8k` | yes |
| Insider latest | `/stable/insider-trading/latest` | yes |
| M&A latest | `/stable/mergers-acquisitions-latest` | yes |
| Senate/House | `/stable/senate-latest` `/stable/house-latest` | yes |
| Earnings calendar | `/stable/earnings-calendar` | yes (filter, not dump 4k) |
| Press releases latest | `/stable/news/press-releases-latest` | **402** |
| Transcripts latest | `/stable/earning-call-transcript-latest` | **402** |
| Latest financials | `/stable/latest-financial-statements` | **402** |
| 13F holders | `/stable/institutional-ownership/…` | **402** |

Check (rate-metered) now fills the FIFO then asks local thinking to
compact. Watchlist 10-K/Q extract remains `prospects-update` on the
extract claim. `apply_and_admit` skips `kubectl apply` when that claim
pod is already Running.
