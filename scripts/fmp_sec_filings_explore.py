"""Explore FMP SEC filings API responses.

Fetches sample 10-K/10-Q filings for test tickers and documents
the response schema for Iceberg table design.

Usage:
    uv run python scripts/fmp_sec_filings_explore.py
    uv run python scripts/fmp_sec_filings_explore.py --ticker CHTR
    uv run python scripts/fmp_sec_filings_explore.py --output scripts/output/fmp/

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
        print("  Run: uv run python scripts/check_fmp.py")
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


def fetch_sec_filings(
    symbol: str,
    api_key: str,
    form_type: str | None = None,
    limit: int = 5,
) -> list[dict] | None:
    """Fetch SEC filings for a symbol.

    Args:
        symbol: Stock symbol (e.g., AAPL, MSFT)
        api_key: FMP API key
        form_type: Filter by form type (10-K, 10-Q, 8-K)
        limit: Max filings to return

    Returns:
        List of filing dictionaries or None on error
    """
    url = f"{FMP_BASE_URL}/v3/sec_filings/{symbol}"
    params = {"apikey": api_key, "limit": limit}

    if form_type:
        params["type"] = form_type

    try:
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 429:
            print(f"  Rate limit exceeded for {symbol}")
            return None

        if response.status_code != 200:
            print(f"  Error {response.status_code} for {symbol}")
            return None

        return response.json()

    except requests.RequestException as e:
        print(f"  Request failed for {symbol}: {e}")
        return None


def analyze_schema(filings: list[dict]) -> dict:
    """Analyze the schema of filing responses.

    Returns a dictionary documenting field types and examples.
    """
    if not filings:
        return {}

    schema = {}

    for filing in filings:
        for key, value in filing.items():
            if key not in schema:
                schema[key] = {
                    "type": type(value).__name__,
                    "nullable": False,
                    "examples": [],
                }

            # Track nullability
            if value is None:
                schema[key]["nullable"] = True

            # Collect unique examples (up to 3)
            if value is not None and len(schema[key]["examples"]) < 3:
                example = str(value)[:100]  # Truncate long values
                if example not in schema[key]["examples"]:
                    schema[key]["examples"].append(example)

    return schema


def print_schema_table(schema: dict) -> None:
    """Print schema as a markdown table."""
    print()
    print("| Field | Type | Nullable | Example |")
    print("|-------|------|----------|---------|")

    for field, info in sorted(schema.items()):
        field_type = info["type"]
        nullable = "Yes" if info["nullable"] else "No"
        example = info["examples"][0] if info["examples"] else "N/A"
        # Truncate example for display
        if len(example) > 40:
            example = example[:37] + "..."
        print(f"| {field} | {field_type} | {nullable} | {example} |")


def save_output(
    data: dict,
    output_dir: Path,
    filename: str,
) -> None:
    """Save JSON output to file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Saved: {output_path}")


def main() -> int:
    """Run FMP SEC filings exploration."""
    parser = argparse.ArgumentParser(description="Explore FMP SEC filings API")
    parser.add_argument(
        "--symbol",
        type=str,
        help="Single symbol to explore (default: all from watchlist)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="scripts/output/fmp",
        help="Output directory for JSON files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max filings per ticker (default: 5)",
    )
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        return 1

    output_dir = Path(args.output)

    # Get symbols: CLI arg or config file
    if args.symbol:
        symbols = [args.symbol]
    else:
        symbols = load_watchlist_symbols()

    print("=" * 60)
    print("FMP SEC Filings Explorer")
    print("=" * 60)
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Output: {output_dir}")
    print()

    all_filings = {}
    combined_schema = {}

    for symbol in symbols:
        print(f"Fetching {symbol}...")

        # Fetch different form types
        for form_type in ["10-K", "10-Q", "8-K"]:
            filings = fetch_sec_filings(symbol, api_key, form_type, limit=args.limit)

            if filings:
                key = f"{symbol}_{form_type}"
                all_filings[key] = filings
                print(f"  {form_type}: {len(filings)} filings")

                # Build combined schema
                schema = analyze_schema(filings)
                for field, info in schema.items():
                    if field not in combined_schema:
                        combined_schema[field] = info

    # Print combined schema
    print()
    print("=" * 60)
    print("Combined Schema (all form types)")
    print("=" * 60)
    print_schema_table(combined_schema)

    # Save outputs
    print()
    print("=" * 60)
    print("Saving outputs...")
    print("=" * 60)

    # Save raw filings
    save_output(all_filings, output_dir, "sec_filings_raw.json")

    # Save schema documentation
    schema_doc = {
        "generated_at": datetime.now().isoformat(),
        "symbols_sampled": symbols,
        "form_types": ["10-K", "10-Q", "8-K"],
        "schema": combined_schema,
        "iceberg_mapping": {
            "id": "UUID (generated)",
            "symbol": "symbol field",
            "cik": "cik field",
            "form_type": "type field",
            "filing_date": "fillingDate field (note: FMP uses 'filling')",
            "accession_number": "link field (extract from URL)",
            "fiscal_period": "Derived from finalLink or fillingDate",
            "raw_response": "Full JSON response",
            "content_hash": "SHA-256 of raw_response",
            "fetched_at": "Timestamp when fetched",
        },
    }
    save_output(schema_doc, output_dir, "sec_filings_schema.json")

    print()
    print("Done! Schema documented for Iceberg table design.")
    print()
    print("Key observations:")
    print("  - FMP uses 'fillingDate' (not 'filingDate')")
    print("  - Accession number can be extracted from 'link' URL")
    print("  - 'finalLink' contains direct SEC EDGAR link")

    return 0


if __name__ == "__main__":
    sys.exit(main())
