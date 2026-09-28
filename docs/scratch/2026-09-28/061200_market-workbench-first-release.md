# Market workbench, first cut

The 68-view narrative is a design, not a description of a session and not a claim about a market. Options stay out: FMP's surface used here documents prices, statements, segment revenue, forecasts, and Treasury rates, not an executable chain. Hypothetical premiums are not observations.

`gaius_market_briefing` is in the workload catalog and **paused**. Enabling it would let Airflow create a run for an interval already past. A stray task returns skipped so it cannot look like a finished briefing.

The first figures a session can draw from data it passes in are the return board, price structure (candle, average, volume), indexed relative performance, a cash-conversion bridge, ROIC against WACC, a consensus curve only when two vintages are stored, and a reverse DCF heatmap of admissible cells. Breadth that needs historical index membership is specified and not drawn. A live estimate pull is a snapshot, not a revision history.
