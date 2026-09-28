"""Formulas and catalog rules. No market fetch."""
from __future__ import annotations

import pytest

from gaius.agents.market.briefing import narrative_card, render_briefing
from gaius.agents.market.catalog import FIRST, OPTIONS_BLOCK, first_release, options_blocked
from gaius.agents.market.valuation import (
    ValuationError,
    fcff,
    reinvestment_rate,
    reverse_dcf_grid,
    reverse_dcf_value,
    terminal_value,
)


def test_fcff_matches_the_operating_identity():
    # 100 * 0.8 + 10 - 20 - 5 = 65
    assert fcff(100, 0.2, 10, 20, 5) == 65


def test_growth_implies_reinvestment_and_terminal_rate_must_exceed_growth():
    assert reinvestment_rate(0.04, 0.10) == pytest.approx(0.4)
    with pytest.raises(ValuationError):
        reinvestment_rate(0.04, 0.0)
    with pytest.raises(ValuationError):
        terminal_value(10, discount=0.03, growth=0.04)


def test_reverse_dcf_masks_cells_that_are_not_admissible():
    blocked = reverse_dcf_value(fcff0=5, growth=0.09, roic=0.10, discount=0.08)
    assert blocked is None
    valued = reverse_dcf_value(fcff0=5, growth=0.03, roic=0.12, discount=0.08, years=5)
    assert valued is not None and valued > 0
    grid = reverse_dcf_grid(
        fcff0=5,
        discount=0.08,
        growths=[0.02, 0.09],
        roics=[0.12],
        years=5,
    )
    by_growth = {g: v for g, _r, v in grid}
    assert by_growth[0.02] is not None
    assert by_growth[0.09] is None


def test_first_release_is_the_daily_six_and_options_are_blocked():
    ids = {view.id for view in first_release()}
    assert ids == {
        "cross_asset_return_board",
        "price_structure",
        "relative_performance",
        "cash_conversion",
        "roic_wacc",
        "consensus_revisions",
        "reverse_dcf",
    }
    assert options_blocked("payoff_comparison")
    assert not options_blocked("reverse_dcf")
    with pytest.raises(ValueError, match="not a verified FMP adapter"):
        narrative_card(
            view_id="payoff_comparison",
            finding="x",
            interpretation="x",
            counterevidence="x",
            implication="x",
            invalidation="x",
        )
    text = render_briefing(
        [
            narrative_card(
                view_id="reverse_dcf",
                finding="one admissible cell",
                interpretation="a combination, not a unique forecast",
                counterevidence="another growth and margin pair can match the same price",
                implication="the price does not identify the duration",
                invalidation="discount rate no longer exceeds growth",
            )
        ]
    )
    assert "reverse_dcf" in text
    assert "Hypothetical" not in text
    assert OPTIONS_BLOCK
    assert FIRST == "first"
