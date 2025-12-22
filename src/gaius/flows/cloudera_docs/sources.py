"""Cloudera Documentation Source Configuration.

Defines product sources for docs.cloudera.com and archive.cloudera.com.
Supports both public HTML docs and authenticated archive downloads.

Archive Access:
    Set CLOUDERA_ARCHIVE_USER and CLOUDERA_ARCHIVE_PASSWORD environment
    variables for authenticated access to archive.cloudera.com.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceType(Enum):
    """Type of documentation source."""
    HTML = "html"      # Crawl HTML pages from docs.cloudera.com
    ARCHIVE = "archive"  # Download ZIP from archive.cloudera.com (requires auth)


@dataclass
class ProductSource:
    """Configuration for a Cloudera product documentation source.

    Attributes:
        name: Short name (e.g., "csa", "kudu")
        display_name: Human-readable name
        domain: Gaius domain this maps to
        source_type: HTML scraping or archive download
        base_url: Base URL for documentation
        version: Product version (e.g., "1.13.0")
        index_path: Path to the index/TOC page
        kb_prefix: KB path prefix for extracted docs
        path_patterns: URL patterns to match for this product
        archive_url: URL to ZIP archive (for ARCHIVE type)
        exclude_patterns: URL patterns to exclude from crawling
    """
    name: str
    display_name: str
    domain: str
    source_type: SourceType
    base_url: str
    version: str
    index_path: str
    kb_prefix: str
    path_patterns: list[str] = field(default_factory=list)
    archive_url: str | None = None
    exclude_patterns: list[str] = field(default_factory=list)
    extra_config: dict[str, Any] = field(default_factory=dict)

    @property
    def index_url(self) -> str:
        """Full URL to the index page."""
        return f"{self.base_url}/{self.index_path}"

    def matches_url(self, url: str) -> bool:
        """Check if URL matches this product's patterns."""
        for pattern in self.path_patterns:
            if pattern in url:
                return True
        return False

    def should_exclude(self, url: str) -> bool:
        """Check if URL should be excluded from crawling."""
        for pattern in self.exclude_patterns:
            if pattern in url:
                return True
        return False


def get_archive_credentials() -> tuple[str, str] | None:
    """Get archive.cloudera.com credentials from environment.

    Returns:
        Tuple of (username, password) or None if not configured.
    """
    user = os.environ.get("CLOUDERA_ARCHIVE_USER")
    password = os.environ.get("CLOUDERA_ARCHIVE_PASSWORD")
    if user and password:
        return (user, password)
    return None


# =============================================================================
# PRODUCT SOURCE DEFINITIONS
# =============================================================================

# CSA: Cloudera Streaming Analytics (Flink + SQL Stream Builder)
CSA_SOURCE = ProductSource(
    name="csa",
    display_name="Cloudera Streaming Analytics",
    domain="csa",
    source_type=SourceType.ARCHIVE,
    base_url="https://docs.cloudera.com/csa",
    version="1.15.1",
    index_path="1.15.1/index.html",
    kb_prefix="current/cloudera/docs/csa",
    path_patterns=["/csa/", "/streaming-analytics/"],
    archive_url="https://docs.cloudera.com/csa/1.15.1/csa-1-15-1.zip",
    exclude_patterns=[
        "/release-notes/",  # Skip release notes (too volatile)
        "/download/",       # Skip download pages
    ],
    extra_config={
        "topics": [
            "how-to-flink",
            "how-to-ssb",
            "monitoring",
            "reference",
        ],
    },
)

# CSA Operator: Kubernetes operators for Flink + SSB
CSA_OPERATOR_SOURCE = ProductSource(
    name="csa-operator",
    display_name="CSA Operator",
    domain="csa",
    source_type=SourceType.ARCHIVE,
    base_url="https://docs.cloudera.com/csa-operator",
    version="1.4",
    index_path="1.4/index.html",
    kb_prefix="current/cloudera/k8s/csa-operator",
    path_patterns=["/csa-operator/"],
    archive_url="https://docs.cloudera.com/csa-operator/1.4/csa-operator-1-4.zip",
    exclude_patterns=[
        "/release-notes/",
    ],
    extra_config={
        "topics": [
            "installation",
            "configuration",
            "operations",
        ],
    },
)

# Kudu: Apache Kudu columnar storage
KUDU_SOURCE = ProductSource(
    name="kudu",
    display_name="Apache Kudu",
    domain="kudu",
    source_type=SourceType.HTML,
    base_url="https://docs.cloudera.com/runtime",
    version="7.1.9",
    index_path="7.1.9/kudu-overview/index.html",
    kb_prefix="current/cloudera/docs/kudu",
    path_patterns=["/kudu/", "/runtime/kudu/"],
    exclude_patterns=[
        "/release-notes/",
    ],
)

# Impala: Apache Impala SQL engine
IMPALA_SOURCE = ProductSource(
    name="impala",
    display_name="Apache Impala",
    domain="impala",
    source_type=SourceType.HTML,
    base_url="https://docs.cloudera.com/runtime",
    version="7.1.9",
    index_path="7.1.9/impala-overview/index.html",
    kb_prefix="current/cloudera/docs/impala",
    path_patterns=["/impala/", "/runtime/impala/"],
    exclude_patterns=[
        "/release-notes/",
    ],
)

# CFM: Cloudera Flow Management (NiFi)
CFM_SOURCE = ProductSource(
    name="cfm",
    display_name="Cloudera Flow Management",
    domain="cfm",
    source_type=SourceType.HTML,
    base_url="https://docs.cloudera.com/cfm",
    version="2.3.0",
    index_path="2.3.0/index.html",
    kb_prefix="current/cloudera/docs/cfm",
    path_patterns=["/cfm/", "/nifi/", "/dataflow/"],
    exclude_patterns=[
        "/release-notes/",
        "/download/",
    ],
)

# CDP: Core platform infrastructure
CDP_SOURCE = ProductSource(
    name="cdp",
    display_name="CDP Private Cloud Base",
    domain="cdp",
    source_type=SourceType.HTML,
    base_url="https://docs.cloudera.com/cdp-private-cloud-base",
    version="7.1.9",
    index_path="7.1.9/index.html",
    kb_prefix="current/cloudera/docs/cdp",
    path_patterns=["/cdp-private-cloud/", "/private-cloud-base/"],
    exclude_patterns=[
        "/release-notes/",
        "/upgrade/",  # Upgrade docs are very version-specific
    ],
)


# Registry of all product sources
PRODUCT_SOURCES: dict[str, ProductSource] = {
    "csa": CSA_SOURCE,
    "csa-operator": CSA_OPERATOR_SOURCE,
    "kudu": KUDU_SOURCE,
    "impala": IMPALA_SOURCE,
    "cfm": CFM_SOURCE,
    "cdp": CDP_SOURCE,
}


def get_source(name: str) -> ProductSource | None:
    """Get a product source by name."""
    return PRODUCT_SOURCES.get(name.lower())


def list_sources() -> list[ProductSource]:
    """List all configured product sources."""
    return list(PRODUCT_SOURCES.values())
