"""Valuation identities for the market workbench.

These are formulas under stated assumptions. They are not observations of
today's prices, and they are not a distribution of next period's price.
A reverse DCF shows combinations of assumptions consistent with one price.
It does not uniquely identify growth, margins, and the discount rate.
"""
from __future__ import annotations


class ValuationError(ValueError):
    """An assumption set that cannot be valued."""


def fcff(ebit: float, tax: float, depreciation: float, capex: float, delta_nwc: float) -> float:
    """Free cash flow to the firm.

    FCFF = EBIT (1 − τ) + D&A − capex − ΔNWC.
    """
    return float(ebit) * (1.0 - float(tax)) + float(depreciation) - float(capex) - float(delta_nwc)


def reinvestment_rate(growth: float, roic: float) -> float:
    """g ≈ reinvestment rate × ROIC. ROIC must be positive to imply a rate."""
    if roic <= 0:
        raise ValuationError("ROIC must be positive to imply a reinvestment rate")
    return float(growth) / float(roic)


def terminal_value(fcff_next: float, discount: float, growth: float) -> float:
    """Gordon terminal value. The discount rate must exceed growth."""
    if discount <= growth:
        raise ValuationError("terminal discount rate must exceed terminal growth")
    return float(fcff_next) / (float(discount) - float(growth))


def reverse_dcf_value(
    *,
    fcff0: float,
    growth: float,
    roic: float,
    discount: float,
    years: int = 10,
) -> float | None:
    """Enterprise value of an explicit FCFF path plus a mature terminal value.

    Reinvestment during the explicit period is g / ROIC. None means the
    cell is masked: the discount rate does not exceed growth, or ROIC
    cannot fund the growth.
    """
    if years < 1 or discount <= growth or roic <= 0:
        return None
    try:
        reinvest = reinvestment_rate(growth, roic)
    except ValuationError:
        return None
    if reinvest < 0:
        return None
    value = 0.0
    fcff = float(fcff0)
    for year in range(1, years + 1):
        fcff = fcff * (1.0 + growth)
        # Growth is already the FCFF growth the caller asserted. Reinvestment
        # is the consistency check, not a second haircut.
        if reinvest > 1.5:
            return None
        value += fcff / (1.0 + discount) ** year
    try:
        terminal = terminal_value(fcff * (1.0 + growth), discount, growth)
    except ValuationError:
        return None
    value += terminal / (1.0 + discount) ** years
    return value


def reverse_dcf_grid(
    *,
    fcff0: float,
    discount: float,
    growths: list[float],
    roics: list[float],
    years: int = 10,
) -> list[tuple[float, float, float | None]]:
    """(growth, ROIC, enterprise value or None when the cell is not admissible)."""
    cells: list[tuple[float, float, float | None]] = []
    for growth in growths:
        for roic in roics:
            cells.append(
                (
                    float(growth),
                    float(roic),
                    reverse_dcf_value(
                        fcff0=fcff0,
                        growth=float(growth),
                        roic=float(roic),
                        discount=discount,
                        years=years,
                    ),
                )
            )
    return cells
