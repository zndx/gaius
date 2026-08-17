# Prospects + 262k thinking (review)

ProspectsUpdate is a host Metaflow `FlowSpec` (`src/gaius/flows/prospects/update_flow.py`),
spawned as a subprocess (`flow_processes.py`). Not `@kubernetes` steps.
Check is in-engine FMP poll (`ProspectsService`); the Metaflow check flow is unused.

## Where context dies

`filing_preprocessor.preprocess_filing` (30k chars, ~8k tokens) from 350–500k
char 10-Q/10-K. Then `ProspectsAnalyzer.analyze_filing` sends that buffer to
Cerebras GLM 4.7. Synthesis (XAI Grok) only sees those already-cut buffers
plus GLM JSON. FMP itself is small (filing list, profile, 13F); the blob is
EDGAR/docling text FMP pointed at.

## First cut

Keep FMP / EDGAR / docling. Replace GLM per-filing analysis with local
`thinking` on a much larger (or near-full) extracted_text. Optionally replace
Grok synthesis with one thinking pass over all per-filing memos + holders.
Sitrep and `.base` YAML stay cheap. Serialize with Ambient: same TP=4, do
not evict thinking.
