"""content_currency on the PUBLISHED SURFACE (2026-09-04 reframe).

The landing page renders every card with a `card-date`: year-less ("Sep 3")
for the current year, "Mon D, YYYY" otherwise. The verifier's helpers are
pure so the parse — the thing a first pass got wrong by matching only dated
years — is pinned here.
"""

from __future__ import annotations

from datetime import date

from gaius.engine.services.objective_service import parse_card_date, surface_cards

TODAY = date(2026, 9, 4)


def test_parse_card_date_both_renderings() -> None:
    assert parse_card_date("Sep 3", TODAY) == date(2026, 9, 3)
    assert parse_card_date("Aug 16", TODAY) == date(2026, 8, 16)
    assert parse_card_date("Sep 27, 2025", TODAY) == date(2025, 9, 27)
    assert parse_card_date("Dec 23, 2025", TODAY) == date(2025, 12, 23)
    assert parse_card_date("", TODAY) is None
    assert parse_card_date("yesterday", TODAY) is None


def test_parse_card_date_yearless_never_in_the_future() -> None:
    # A year-less "Dec 23" read on 2026-09-04 is last December, not next.
    assert parse_card_date("Dec 23", TODAY) == date(2025, 12, 23)
    assert parse_card_date("Sep 4", TODAY) == TODAY


HTML = """
<div class="masonry-column">
<a href="/cards/card_bf24f2e34919" class="card">
  <div class="card-title">When Is Shallow Enough?</div>
  <div class="card-footer"><span class="card-type">arxiv</span> <span class="card-date">Aug 16</span></div>
</a>
<a href="/cards/card_f7514e9a2890" class="card">
  <div class="card-title">Second</div>
  <div class="card-footer"><span class="card-type">arxiv</span> <span class="card-date">Sep 3</span></div>
</a>
<a href="/cards/card_e0dae6c7576a" class="card">
  <div class="card-title">Old</div>
  <div class="card-footer"><span class="card-type">web</span> <span class="card-date">Sep 27, 2025</span></div>
</a>
<a href="/cards/card_000000000000" class="card">
  <div class="card-title">Undated</div>
  <div class="card-footer"><span class="card-type">web</span></div>
</a>
</div>
"""


def test_surface_cards_keeps_page_order_and_dates() -> None:
    cards = surface_cards(HTML, TODAY)
    assert [c for c, _ in cards] == [
        "card_bf24f2e34919",
        "card_f7514e9a2890",
        "card_e0dae6c7576a",
        "card_000000000000",
    ]
    assert [d for _, d in cards] == [
        date(2026, 8, 16),
        date(2026, 9, 3),
        date(2025, 9, 27),
        None,
    ]


def test_surface_cards_dedupes_repeated_ids() -> None:
    cards = surface_cards(HTML + HTML, TODAY)
    assert len(cards) == 4
