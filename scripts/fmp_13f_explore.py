"""Explore FMP 13F institutional holdings API.

Fetches institutional holdings data (13F filings) to understand
the holder structure for prospect intelligence.

Usage:
    uv run python scripts/fmp_13f_explore.py
    uv run python scripts/fmp_13f_explore.py --ticker CHTR
    uv run python scripts/fmp_13f_explore.py --cik 0001445283

Requires FMP_API_KEY environment variable.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

FMP_BASE_URL = "https://financialmodelingprep.com/api"

# Config file path for prospect watchlist
CONFIG_PATH = Path(__file__).parent.parent / "config" / "prospects" / "watchlist.conf"


def get_api_key() -> str | None:
    """Get FMP API key from environment."""
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        print("Error: FMP_API_KEY not set")
        return None
    return api_key


def load_watchlist_symbols() -> list[str]:
    """Load symbols from HOCON config file.

    Fails fast if config file is missing or invalid.
    """
    if not CONFIG_PATH.exists():
        print(f"Error: Config file not found: {CONFIG_PATH}")
        print()
        print("Create your watchlist config:")
        print(f"  cp {CONFIG_PATH}.example {CONFIG_PATH}")
        print("  # Edit with your prospect symbols")
        print()
        raise SystemExit(1)

    try:
        from pyhocon import ConfigFactory
    except ImportError:
        print("Error: pyhocon not installed")
        print("  Install with: uv add pyhocon")
        raise SystemExit(1)

    try:
        config = ConfigFactory.parse_file(str(CONFIG_PATH))
        watchlist = config.get("prospects.watchlist", [])
        symbols = [entry.get("symbol") for entry in watchlist if entry.get("symbol")]

        if not symbols:
            print(f"Error: No symbols found in {CONFIG_PATH}")
            print("  Add entries to prospects.watchlist")
            raise SystemExit(1)

        return symbols

    except Exception as e:
        print(f"Error: Failed to parse {CONFIG_PATH}: {e}")
        raise SystemExit(1)


def fetch_institutional_holders(symbol: str, api_key: str) -> list[dict] | None:
    """Fetch institutional holders for a symbol.

    This endpoint shows which institutions hold the stock.
    """
    url = f"{FMP_BASE_URL}/v3/institutional-holder/{symbol}"
    params = {"apikey": api_key}

    try:
        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"  Error {response.status_code} for institutional holders")
            return None

        return response.json()

    except requests.RequestException as e:
        print(f"  Request failed: {e}")
        return None


def fetch_13f_holdings(cik: str, api_key: str) -> list[dict] | None:
    """Fetch 13F portfolio holdings for an institution by CIK.

    This shows what stocks an institution holds (reverse lookup).
    """
    url = f"{FMP_BASE_URL}/v4/institutional-ownership/portfolio-holdings"
    params = {"cik": cik, "apikey": api_key}

    try:
        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"  Error {response.status_code} for 13F holdings")
            return None

        return response.json()

    except requests.RequestException as e:
        print(f"  Request failed: {e}")
        return None


def fetch_institutional_ownership_percent(symbol: str, api_key: str) -> dict | None:
    """Fetch institutional ownership percentage summary."""
    url = f"{FMP_BASE_URL}/v4/institutional-ownership/symbol-ownership-percent"
    params = {"symbol": symbol, "apikey": api_key}

    try:
        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"  Error {response.status_code} for ownership percent")
            return None

        data = response.json()
        return data[0] if data else None

    except requests.RequestException as e:
        print(f"  Request failed: {e}")
        return None


def analyze_holder_schema(holders: list[dict]) -> dict:
    """Analyze schema of holder responses."""
    if not holders:
        return {}

    schema = {}
    for holder in holders[:10]:  # Sample first 10
        for key, value in holder.items():
            if key not in schema:
                schema[key] = {
                    "type": type(value).__name__,
                    "examples": [],
                }
            if value is not None and len(schema[key]["examples"]) < 2:
                example = str(value)[:60]
                if example not in schema[key]["examples"]:
                    schema[key]["examples"].append(example)

    return schema


def print_top_holders(holders: list[dict], limit: int = 10) -> None:
    """Print top institutional holders."""
    if not holders:
        print("  No holders found")
        return

    print()
    print(f"  Top {min(limit, len(holders))} Institutional Holders:")
    print("  " + "-" * 60)

    for i, holder in enumerate(holders[:limit]):
        name = holder.get("holder", "Unknown")[:40]
        shares = holder.get("shares", 0)
        pct = holder.get("change", 0)
        print(f"  {i+1:2}. {name:<40} {shares:>12,} shares")


def save_output(data: dict, output_dir: Path, filename: str) -> None:
    """Save JSON output to file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Saved: {output_path}")


def main() -> int:
    """Run 13F exploration."""
    parser = argparse.ArgumentParser(description="Explore FMP 13F API")
    parser.add_argument("--symbol", type=str, help="Stock symbol to explore")
    parser.add_argument("--cik", type=str, help="Institution CIK for portfolio lookup")
    parser.add_argument(
        "--output",
        type=str,
        default="scripts/output/fmp",
        help="Output directory",
    )
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        return 1

    output_dir = Path(args.output)

    print("=" * 60)
    print("FMP 13F Holdings Explorer")
    print("=" * 60)
    print()

    all_data = {
        "generated_at": datetime.now().isoformat(),
        "holders": {},
        "ownership": {},
        "schema": {},
    }

    # If specific CIK provided, fetch portfolio
    if args.cik:
        print(f"Fetching portfolio holdings for CIK {args.cik}...")
        holdings = fetch_13f_holdings(args.cik, api_key)
        if holdings:
            print(f"  Found {len(holdings)} holdings")
            all_data["portfolio_holdings"] = holdings[:20]  # Sample
            all_data["schema"]["portfolio"] = analyze_holder_schema(holdings)
        return 0

    # Get symbols: CLI arg or config file
    if args.symbol:
        symbols = [args.symbol]
    else:
        symbols = load_watchlist_symbols()

    for symbol in symbols:
        print(f"Exploring {symbol}...")

        # Fetch institutional holders
        holders = fetch_institutional_holders(symbol, api_key)
        if holders:
            all_data["holders"][symbol] = holders[:20]  # Top 20
            print(f"  Found {len(holders)} institutional holders")
            print_top_holders(holders)

            if "institutional_holders" not in all_data["schema"]:
                all_data["schema"]["institutional_holders"] = analyze_holder_schema(holders)

        # Fetch ownership percentage
        ownership = fetch_institutional_ownership_percent(symbol, api_key)
        if ownership:
            all_data["ownership"][symbol] = ownership
            pct = ownership.get("investorsHoldingPercentage", 0)
            print(f"  Institutional ownership: {pct:.1%}")

        print()

    # Schema documentation
    print("=" * 60)
    print("Schema Documentation")
    print("=" * 60)

    if "institutional_holders" in all_data["schema"]:
        print()
        print("Institutional Holders Schema:")
        for field, info in all_data["schema"]["institutional_holders"].items():
            examples = ", ".join(info["examples"][:2])
            print(f"  {field} ({info['type']}): {examples}")

    # Save outputs
    print()
    print("=" * 60)
    print("Saving outputs...")
    print("=" * 60)
    save_output(all_data, output_dir, "13f_holdings.json")

    print()
    print("Key observations:")
    print("  - Use institutional-holder/{ticker} for who owns a stock")
    print("  - Use portfolio-holdings?cik={cik} for what an institution owns")
    print("  - 13F filings are quarterly (45 days after quarter end)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
