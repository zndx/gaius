"""Check FMP API connectivity and quota.

Validates FMP_API_KEY and tests basic endpoint connectivity.
Requires FMP_API_KEY environment variable.

Usage:
    uv run python scripts/check_fmp.py
"""

import json
import os
import sys

import requests

FMP_BASE_URL = "https://financialmodelingprep.com/api"


def check_api_key() -> str | None:
    """Check if FMP API key is configured."""
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        print("Error: FMP_API_KEY environment variable not set")
        print("  Get a free key at: https://financialmodelingprep.com/developer")
        print("  Then: export FMP_API_KEY=your_key_here")
        return None
    return api_key


def test_profile_endpoint(api_key: str) -> bool:
    """Test basic API connectivity with company profile."""
    url = f"{FMP_BASE_URL}/v3/profile/AAPL?apikey={api_key}"

    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 401:
            print("Error: Invalid API key")
            return False

        if response.status_code == 429:
            print("Error: Rate limit exceeded (250 requests/day on free tier)")
            return False

        if response.status_code != 200:
            print(f"Error: Unexpected status code {response.status_code}")
            return False

        data = response.json()
        if data:
            company = data[0]
            print(f"Profile endpoint OK: {company.get('companyName', 'Unknown')}")
            return True
        else:
            print("Warning: Empty response from profile endpoint")
            return False

    except requests.RequestException as e:
        print(f"Error: Network request failed: {e}")
        return False


def test_sec_filings_endpoint(api_key: str) -> bool:
    """Test SEC filings endpoint."""
    url = f"{FMP_BASE_URL}/v3/sec_filings/AAPL?type=10-K&limit=1&apikey={api_key}"

    try:
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            print(f"Error: SEC filings endpoint returned {response.status_code}")
            return False

        data = response.json()
        if data:
            filing = data[0]
            print(f"SEC filings endpoint OK: Found {filing.get('type', 'Unknown')} from {filing.get('fillingDate', 'Unknown')}")
            return True
        else:
            print("Warning: No SEC filings found for AAPL (unexpected)")
            return False

    except requests.RequestException as e:
        print(f"Error: SEC filings request failed: {e}")
        return False


def check_remaining_quota(api_key: str) -> None:
    """Check remaining API quota (if available in headers)."""
    # FMP doesn't expose quota in headers, but we can check profile
    # to confirm the key is still valid within limits
    url = f"{FMP_BASE_URL}/v3/profile/MSFT?apikey={api_key}"

    try:
        response = requests.get(url, timeout=10)

        # Check for rate limit headers (may not be present)
        remaining = response.headers.get("X-RateLimit-Remaining")
        limit = response.headers.get("X-RateLimit-Limit")

        if remaining and limit:
            print(f"Quota: {remaining}/{limit} requests remaining")
        else:
            print("Note: FMP doesn't expose quota in response headers")
            print("  Free tier: 250 requests/day")

    except requests.RequestException:
        pass


def main() -> int:
    """Run FMP API connectivity check."""
    print("=" * 50)
    print("FMP API Connectivity Check")
    print("=" * 50)
    print()

    # Check API key
    api_key = check_api_key()
    if not api_key:
        return 1

    print(f"API Key: {api_key[:8]}...{api_key[-4:]}")
    print()

    # Test endpoints
    results = []

    print("Testing endpoints...")
    results.append(("Profile", test_profile_endpoint(api_key)))
    results.append(("SEC Filings", test_sec_filings_endpoint(api_key)))

    print()
    check_remaining_quota(api_key)

    # Summary
    print()
    print("=" * 50)
    print("Summary")
    print("=" * 50)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print()
        print("All checks passed! FMP API is ready for use.")
        return 0
    else:
        print()
        print("Some checks failed. See errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
