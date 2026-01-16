"""HuggingFace Hub integration for dataset discovery.

Provides functions to list and fetch metadata for datasets on HuggingFace Hub.
Used by /datasets command for triage of external datasets.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from huggingface_hub import HfApi, DatasetInfo as HFDatasetInfo

logger = logging.getLogger(__name__)


@dataclass
class DatasetInfo:
    """Simplified dataset metadata for display and KB storage."""

    id: str  # e.g., "facebook/research-plan-gen"
    description: str
    downloads: int
    created_at: datetime | None
    last_modified: datetime | None
    tags: list[str] = field(default_factory=list)
    author: str = ""
    likes: int = 0
    private: bool = False

    @classmethod
    def from_hf(cls, info: HFDatasetInfo) -> "DatasetInfo":
        """Create from HuggingFace DatasetInfo object.

        Note: list_datasets() returns lightweight info without description.
        Use get_dataset_info() for full metadata including description.
        """
        # Description is only available from dataset_info(), not list_datasets()
        description = getattr(info, "description", None) or ""
        return cls(
            id=info.id,
            description=description,
            downloads=info.downloads or 0,
            created_at=info.created_at,
            last_modified=info.last_modified,
            tags=list(info.tags) if info.tags else [],
            author=info.author or "",
            likes=info.likes or 0,
            private=info.private or False,
        )

    def to_markdown(self) -> str:
        """Format as markdown for zettelkasten note."""
        lines = [f"### {self.id}"]

        if self.description:
            # Truncate long descriptions
            desc = self.description[:300]
            if len(self.description) > 300:
                desc += "..."
            lines.append(f"*{desc}*")

        lines.append("")
        lines.append(f"- **Downloads**: {self.downloads:,}")
        lines.append(f"- **Likes**: {self.likes}")

        if self.created_at:
            lines.append(f"- **Created**: {self.created_at.strftime('%Y-%m-%d')}")
        if self.last_modified:
            lines.append(f"- **Updated**: {self.last_modified.strftime('%Y-%m-%d')}")

        if self.tags:
            tag_str = ", ".join(self.tags[:10])  # Limit tags shown
            if len(self.tags) > 10:
                tag_str += f" (+{len(self.tags) - 10} more)"
            lines.append(f"- **Tags**: {tag_str}")

        if self.author:
            lines.append(f"- **Author**: {self.author}")

        lines.append("")
        lines.append(f"> Add with: `/datasets add {self.id}`")
        lines.append("")

        return "\n".join(lines)

    def to_kb_entry(self, notes: str = "") -> str:
        """Format as KB entry for current/datasets/external/."""
        lines = [
            f"# {self.id}",
            "",
            f"**Source**: https://huggingface.co/datasets/{self.id}",
            f"**Added**: {datetime.now().strftime('%Y-%m-%d')}",
            "**Status**: candidate",
            "",
        ]

        if self.created_at:
            lines.append(f"**Created**: {self.created_at.strftime('%Y-%m-%d')}")
        if self.last_modified:
            lines.append(f"**Last Modified**: {self.last_modified.strftime('%Y-%m-%d')}")

        lines.extend([
            f"**Downloads**: {self.downloads:,}",
            f"**Likes**: {self.likes}",
            "",
            "## Description",
            "",
            self.description or "(No description)",
            "",
        ])

        if self.tags:
            lines.extend([
                "## Tags",
                "",
                ", ".join(self.tags),
                "",
            ])

        if notes:
            lines.extend([
                "## Notes",
                "",
                notes,
                "",
            ])

        lines.extend([
            "## Relevance",
            "",
            "(Add notes on why this dataset is interesting)",
            "",
            "## Use Cases",
            "",
            "- [ ] (Add potential use cases)",
            "",
        ])

        return "\n".join(lines)


def list_recent_datasets(limit: int = 20) -> list[DatasetInfo]:
    """Fetch recent datasets from HuggingFace Hub.

    No filtering - returns raw most recent datasets for manual triage.

    Args:
        limit: Maximum number of datasets to return (default 20)

    Returns:
        List of DatasetInfo objects sorted by creation date (newest first)
    """
    api = HfApi()

    try:
        # Fetch datasets sorted by creation date
        datasets = api.list_datasets(
            sort="createdAt",
            direction=-1,  # Descending (newest first)
            limit=limit,
        )

        results = []
        for ds in datasets:
            try:
                results.append(DatasetInfo.from_hf(ds))
            except Exception as e:
                logger.warning(f"Failed to parse dataset {getattr(ds, 'id', 'unknown')}: {e}")
                continue

        return results

    except Exception as e:
        logger.error(f"Failed to fetch datasets from HuggingFace: {e}")
        raise RuntimeError(
            f"HuggingFace API error: {e}\n"
            "Check: network connectivity, HF_TOKEN if rate-limited"
        ) from e


def get_dataset_info(dataset_id: str) -> DatasetInfo:
    """Fetch detailed info for a specific dataset.

    Args:
        dataset_id: Full dataset ID (e.g., "facebook/research-plan-gen")

    Returns:
        DatasetInfo object with full metadata
    """
    api = HfApi()

    try:
        info = api.dataset_info(dataset_id)
        return DatasetInfo.from_hf(info)
    except Exception as e:
        logger.error(f"Failed to fetch dataset {dataset_id}: {e}")
        raise RuntimeError(
            f"Dataset not found: {dataset_id}\n"
            f"Error: {e}"
        ) from e
