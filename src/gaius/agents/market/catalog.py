"""Catalog of market-narrative views.

Design recommendations for a workbench. Not observations of a market.
Options views stay blocked until an options-chain adapter is verified.
FMP's public surface, as checked for this catalog, documents equity
prices, statements, segment revenue, forecasts, and Treasury rates.
It does not document an executable options chain.
"""
from __future__ import annotations

from dataclasses import dataclass

FIRST = "first"
LATER = "later"
OPTIONS = "options"


@dataclass(frozen=True)
class ViewSpec:
    id: str
    question: str
    composition: str
    release: str
    needs: str


def _v(id: str, question: str, composition: str, release: str, needs: str) -> ViewSpec:
    return ViewSpec(id, question, composition, release, needs)


# The first release is the daily briefing. Later views are specified so a
# session does not invent a chart that the warehouse cannot support yet.
VIEWS: tuple[ViewSpec, ...] = (
    _v("cross_asset_return_board", "moved", "HeatMap + Labels", FIRST, "eod closes for the named basket"),
    _v("sector_contribution_waterfall", "moved", "Rectangles + Segments", LATER, "prior weights and returns"),
    _v("breadth_dashboard", "moved", "Curve + HLine", LATER, "historical index membership, not yet reconciled"),
    _v("concentration_equal_weight", "moved", "Curve + Area", LATER, "historical membership"),
    _v("sector_rotation_trails", "moved", "Points + Path", LATER, "sector relative strength history"),
    _v("treasury_curve", "moved", "Overlaid Curve", LATER, "Treasury rates"),
    _v("correlation_beta_dispersion", "moved", "HeatMap + BoxWhisker", LATER, "return panel"),
    _v("regime_catalyst_timeline", "moved", "Area + Spikes + Labels", LATER, "regime model plus event calendar"),
    _v("price_structure", "moved", "Segments + Rectangles + Curve + Bars", FIRST, "daily OHLCV"),
    _v("momentum_panel", "moved", "Curve + reference lines", LATER, "adjusted closes"),
    _v("volatility_range", "moved", "Curve + Area", LATER, "daily OHLC"),
    _v("relative_performance", "moved", "Curve", FIRST, "closes, indexed to 100"),
    _v("anchored_vwap", "moved", "Curve + horizontal Bars", LATER, "intraday prints; daily OHLCV cannot reconstruct them"),
    _v("breakout_retest", "moved", "Curve + Points + bands", LATER, "adjusted closes"),
    _v("conditional_forward_returns", "moved", "BoxWhisker + ErrorBars", LATER, "explicit signal history and sample size"),
    _v("parameter_stability", "moved", "HeatMap", LATER, "a versioned indicator and a grid of lookbacks"),
    _v("liquidity_gaps", "moved", "Scatter + HeatMap", LATER, "daily OHLCV is only a gap proxy"),
    _v("event_aligned_paths", "moved", "Overlaid Curve + Area", LATER, "event dates and benchmark-adjusted returns"),
    _v("revenue_mix", "business", "Stacked Area + Bars", LATER, "segment revenue"),
    _v("operating_driver_bridge", "business", "Rectangles + Segments", LATER, "company-specific drivers"),
    _v("margin_progression", "business", "Curve + Scatter", LATER, "statements"),
    _v("cash_conversion", "business", "Rectangles + Segments", FIRST, "explicit bridge amounts, not a fetched statement"),
    _v("working_capital_cycle", "business", "Curve + Bars", LATER, "statements"),
    _v("roic_wacc", "business", "Scatter + Curve", FIRST, "explicit ROIC and WACC series"),
    _v("dupont", "business", "Bars + Scatter", LATER, "statements"),
    _v("dilution_allocation", "business", "Bars + Curve", LATER, "share count and capital returns"),
    _v("solvency", "business", "Bars + HeatMap", LATER, "maturities may need the filing"),
    _v("earnings_quality", "business", "HeatMap + Scatter", LATER, "accruals"),
    _v("consensus_revisions", "expectations", "Curve + ErrorBars", FIRST, "stored estimate snapshots; a live pull is not history"),
    _v("guidance_ledger", "business", "Table + Points", LATER, "management statements and later outcomes"),
    _v("forecast_fan", "expectations", "Curve + Area", LATER, "stated scenarios"),
    _v("equity_bridge", "expectations", "Rectangles", LATER, "stated bridge"),
    _v("dcf_sensitivity", "expectations", "HeatMap", LATER, "stated assumptions"),
    _v("reverse_dcf", "expectations", "HeatMap", FIRST, "stated FCFF, discount, growth, and ROIC grid"),
    _v("valuation_distribution", "expectations", "Histogram + VLine", LATER, "a specified assumption distribution, not a price forecast"),
    _v("economic_profit_persistence", "expectations", "Curve + Area", LATER, "stated ROIC path"),
    _v("peer_frontier", "expectations", "Scatter", LATER, "peer fundamentals"),
    _v("residual_income", "expectations", "Curve + Bars", LATER, "equity excess returns"),
    _v("sum_of_parts", "expectations", "Rectangles", LATER, "stated segment values"),
    _v("rnpv", "expectations", "Graph + Table", LATER, "stated development scenarios"),
    _v("price_versus_value", "expectations", "Curve + bands", LATER, "a value that existed at the time, not today's model"),
    _v("value_attribution", "expectations", "Rectangles", LATER, "stated attribution"),
    _v("business_specific", "expectations", "NdLayout", LATER, "the business model that applies"),
    _v("valuation_duration", "expectations", "Curve + HeatMap", LATER, "stated cash-flow timing"),
    _v("chain_liquidity", "exposure", "HeatMap + Table", OPTIONS, "verified options quotes"),
    _v("iv_smile", "exposure", "Curve + Points", OPTIONS, "verified options quotes"),
    _v("vol_surface", "exposure", "HeatMap + Contours", OPTIONS, "verified options quotes"),
    _v("term_structure", "exposure", "Curve", OPTIONS, "verified options quotes"),
    _v("implied_versus_realized", "exposure", "Curve + Area", OPTIONS, "verified options quotes and a documented forecast"),
    _v("greeks_grid", "exposure", "HeatMap + Curve", OPTIONS, "a stated pricing model, labeled as model output"),
    _v("physical_versus_risk_neutral", "exposure", "Curve + Area", OPTIONS, "verified quotes plus an explicit forecast"),
    _v("pricing_residuals", "exposure", "Scatter + HeatMap", OPTIONS, "verified quotes"),
    _v("option_pnl_attribution", "exposure", "Rectangles", OPTIONS, "observed or explicitly hypothetical premiums"),
    _v("open_interest_profile", "exposure", "Bars + HeatMap", OPTIONS, "verified open interest; not dealer direction"),
    _v("payoff_comparison", "exposure", "Curve", OPTIONS, "hypothetical payoff must be labeled hypothetical"),
    _v("strike_expiry_map", "exposure", "HeatMap", OPTIONS, "verified quotes"),
    _v("value_aware_strike", "exposure", "Curve + Points", OPTIONS, "verified quotes"),
    _v("premium_upside_frontier", "exposure", "Scatter", OPTIONS, "verified or labeled-hypothetical premiums"),
    _v("assignment_calendar", "exposure", "Spikes + Table", OPTIONS, "expiry and dividend dates"),
    _v("total_return_attribution", "exposure", "Bars + Curve", OPTIONS, "complete cash flows"),
    _v("roll_surface", "exposure", "HeatMap", OPTIONS, "verified quotes"),
    _v("policy_backtest", "exposure", "Curve + Area", OPTIONS, "a stated rule and a price history"),
    _v("portfolio_stress", "exposure", "HeatMap + Bars", OPTIONS, "stated shocks"),
    _v("coverage_frontier", "exposure", "Curve + Scatter", OPTIONS, "stated coverage ratios"),
)

OPTIONS_BLOCK = (
    "Options quotes are not a verified FMP adapter. "
    "An executable chain was not in the public FMP documentation checked "
    "for this workbench. Hypothetical premiums are not drawn as observations."
)


def by_id(view_id: str) -> ViewSpec | None:
    key = (view_id or "").strip()
    for view in VIEWS:
        if view.id == key:
            return view
    return None


def first_release() -> tuple[ViewSpec, ...]:
    return tuple(view for view in VIEWS if view.release == FIRST)


def options_blocked(view_id: str) -> bool:
    view = by_id(view_id)
    return view is not None and view.release == OPTIONS
