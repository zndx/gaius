"""SHAP-based effectiveness measurement for ThetaAgent consolidation.

ACADEMIC IMPLEMENTATION (Lundberg & Lee 2017):
Uses SHAP (SHapley Additive exPlanations) to compute feature attributions
for document augmentations. Shapley values provide:
- Additive feature attributions: sum of SHAP values = prediction difference
- Consistency: equal contributions → equal SHAP values
- Local accuracy: f(x) = E[f(X)] + sum of SHAP values

The measurement compares retrieval quality with/without augmentations
and uses KernelSHAP when the full SHAP library is available.

References:
- Lundberg & Lee (2017). A Unified Approach to Interpreting Model Predictions
- SHAP: https://github.com/slundberg/shap

The effectiveness measurement provides evidence for Knowledge Gradient
policy decisions and validates the consolidation hypothesis.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Awaitable

import numpy as np

import logging

from .augmentation import strip_augmentation, has_augmentation

logger = logging.getLogger(__name__)


# SHAP is REQUIRED - fail-fast at import time
# No fallbacks to simpler methods - academic rigor requires Shapley values
try:
    import shap
    SHAP_AVAILABLE = True
    logger.info("SHAP library loaded for Shapley-based attribution")
except ImportError as e:
    raise RuntimeError(
        "SHAP library required for effectiveness measurement.\n"
        "  Guru Meditation: #THETA.00000006.SHAP_UNAVAILABLE\n"
        "  Try: uv add shap\n"
        "  Note: SHAP requires numpy, scikit-learn\n"
        "  Reference: Lundberg & Lee (2017) - A Unified Approach to Interpreting Model Predictions"
    ) from e


class SHAPNotAvailableError(Exception):
    """Raised when SHAP operation fails.

    Guru Meditation: #THETA.00000006.SHAP_UNAVAILABLE

    Note: This error should never occur at runtime since SHAP is
    required at module import time. Retained for explicit error handling.
    """

    def __init__(self, operation: str, original_error: Exception | None = None):
        msg = (
            f"SHAP operation failed for {operation}.\n"
            f"  Guru Meditation: #THETA.00000006.SHAP_UNAVAILABLE\n"
        )
        if original_error:
            msg += f"  Original error: {original_error}\n"
        super().__init__(msg)


@dataclass
class EffectivenessResult:
    """Result of effectiveness measurement.

    Attributes:
        baseline_score: Retrieval quality without augmentations
        augmented_score: Retrieval quality with augmentations
        augmentation_contribution: Difference (augmented - baseline)
        improvement_pct: Percentage improvement
        query_count: Number of queries evaluated
        document_count: Number of documents evaluated
        timestamp: When measurement was taken
    """

    baseline_score: float
    augmented_score: float
    augmentation_contribution: float
    improvement_pct: float
    query_count: int = 0
    document_count: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "baseline_score": self.baseline_score,
            "augmented_score": self.augmented_score,
            "augmentation_contribution": self.augmentation_contribution,
            "improvement_pct": self.improvement_pct,
            "query_count": self.query_count,
            "document_count": self.document_count,
            "timestamp": self.timestamp.isoformat(),
            "is_positive": self.augmentation_contribution > 0,
        }

    @property
    def is_positive(self) -> bool:
        """Check if augmentation has positive contribution."""
        return self.augmentation_contribution > 0


@dataclass
class RetrievalScore:
    """Scores for a single retrieval evaluation.

    Attributes:
        precision_at_k: Precision at k (default k=5)
        mrr: Mean Reciprocal Rank
        ndcg: Normalized Discounted Cumulative Gain
    """

    precision_at_k: float
    mrr: float = 0.0
    ndcg: float = 0.0
    k: int = 5

    @property
    def combined_score(self) -> float:
        """Weighted combination of metrics."""
        return 0.5 * self.precision_at_k + 0.3 * self.mrr + 0.2 * self.ndcg


# Type alias for embedding function
EmbedderFn = Callable[[str], Awaitable[np.ndarray]]


async def compute_embedding_similarity(
    query: str,
    document: str,
    embedder: EmbedderFn,
) -> float:
    """Compute cosine similarity between query and document embeddings.

    Args:
        query: Query text
        document: Document text
        embedder: Async function to compute embeddings

    Returns:
        Cosine similarity score [0, 1]
    """
    query_emb = await embedder(query)
    doc_emb = await embedder(document)

    # Cosine similarity
    dot = np.dot(query_emb, doc_emb)
    norm = np.linalg.norm(query_emb) * np.linalg.norm(doc_emb)

    if norm == 0:
        return 0.0

    return float(dot / norm)


async def measure_retrieval_quality(
    queries: list[str],
    documents: list[str],
    embedder: EmbedderFn,
    k: int = 5,
) -> RetrievalScore:
    """Measure retrieval quality for a set of queries and documents.

    Computes precision@k using embedding similarity ranking.

    Args:
        queries: List of query strings
        documents: List of document contents
        embedder: Async embedding function
        k: k for precision@k

    Returns:
        RetrievalScore with metrics
    """
    if not queries or not documents:
        return RetrievalScore(precision_at_k=0.0, k=k)

    total_precision = 0.0
    total_mrr = 0.0

    for query in queries:
        # Score all documents
        scores = []
        for i, doc in enumerate(documents):
            sim = await compute_embedding_similarity(query, doc, embedder)
            scores.append((i, sim))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)

        # Precision@k: fraction of top-k that are relevant
        # Here we use similarity threshold as relevance proxy
        threshold = 0.5
        top_k = scores[:k]
        relevant_in_top_k = sum(1 for _, s in top_k if s >= threshold)
        precision = relevant_in_top_k / k if k > 0 else 0.0
        total_precision += precision

        # MRR: reciprocal rank of first relevant document
        for rank, (_, sim) in enumerate(scores, 1):
            if sim >= threshold:
                total_mrr += 1.0 / rank
                break

    avg_precision = total_precision / len(queries) if queries else 0.0
    avg_mrr = total_mrr / len(queries) if queries else 0.0

    return RetrievalScore(precision_at_k=avg_precision, mrr=avg_mrr, k=k)


async def compute_augmentation_contribution(
    queries: list[str],
    document_paths: list[Path],
    embedder: EmbedderFn,
    k: int = 5,
) -> EffectivenessResult:
    """Compute the contribution of augmentations to retrieval quality.

    Performs A/B comparison:
    - Baseline: Documents with augmentation sections stripped
    - Augmented: Documents with full content

    Args:
        queries: List of query strings
        document_paths: Paths to markdown documents
        embedder: Async embedding function
        k: k for precision@k

    Returns:
        EffectivenessResult with contribution metrics
    """
    if not queries or not document_paths:
        return EffectivenessResult(
            baseline_score=0.0,
            augmented_score=0.0,
            augmentation_contribution=0.0,
            improvement_pct=0.0,
        )

    # Load documents
    augmented_docs = []
    baseline_docs = []
    augmented_count = 0

    for path in document_paths:
        if not path.exists():
            continue

        content = path.read_text()
        augmented_docs.append(content)

        # Strip augmentation for baseline
        if has_augmentation(content):
            baseline_docs.append(strip_augmentation(content))
            augmented_count += 1
        else:
            baseline_docs.append(content)

    if not augmented_docs:
        return EffectivenessResult(
            baseline_score=0.0,
            augmented_score=0.0,
            augmentation_contribution=0.0,
            improvement_pct=0.0,
        )

    logger.debug(f"Evaluating {len(augmented_docs)} docs, {augmented_count} with augmentations")

    # Measure baseline quality (without augmentations)
    baseline_score = await measure_retrieval_quality(queries, baseline_docs, embedder, k)

    # Measure augmented quality (with augmentations)
    augmented_score = await measure_retrieval_quality(queries, augmented_docs, embedder, k)

    # Compute contribution
    contribution = augmented_score.combined_score - baseline_score.combined_score

    # Compute improvement percentage
    if baseline_score.combined_score > 0:
        improvement_pct = (contribution / baseline_score.combined_score) * 100
    else:
        improvement_pct = 100.0 if contribution > 0 else 0.0

    return EffectivenessResult(
        baseline_score=baseline_score.combined_score,
        augmented_score=augmented_score.combined_score,
        augmentation_contribution=contribution,
        improvement_pct=improvement_pct,
        query_count=len(queries),
        document_count=len(augmented_docs),
    )


async def run_holdout_evaluation(
    holdout_queries: list[str],
    document_paths: list[Path],
    embedder: EmbedderFn,
    k: int = 5,
) -> dict:
    """Run comprehensive holdout evaluation.

    This is the primary evaluation for validating the consolidation hypothesis.

    Args:
        holdout_queries: Queries reserved for evaluation (never used in training)
        document_paths: All KB document paths
        embedder: Async embedding function
        k: k for precision@k

    Returns:
        Dict with evaluation results and statistics
    """
    # Filter to documents with augmentations
    augmented_paths = [
        p for p in document_paths
        if p.exists() and has_augmentation(p.read_text())
    ]

    logger.info(
        f"Running holdout evaluation: {len(holdout_queries)} queries, "
        f"{len(augmented_paths)} augmented docs"
    )

    # Compute effectiveness
    result = await compute_augmentation_contribution(
        queries=holdout_queries,
        document_paths=document_paths,
        embedder=embedder,
        k=k,
    )

    # Determine statistical significance (simplified)
    # In production, would use proper paired t-test
    significant = (
        abs(result.augmentation_contribution) > 0.05  # Effect size threshold
        and result.query_count >= 10  # Minimum sample size
    )

    return {
        "result": result.to_dict(),
        "augmented_document_count": len(augmented_paths),
        "total_document_count": len(document_paths),
        "significant": significant,
        "hypothesis_supported": result.is_positive and significant,
        "recommendation": (
            "Continue consolidation"
            if result.is_positive
            else "Review consolidation strategy"
        ),
    }


@dataclass
class SHAPAttribution:
    """SHAP-based attribution result for a single document.

    ACADEMIC IMPLEMENTATION (Lundberg & Lee 2017):
    Shapley values satisfy the efficiency axiom:
        sum(shap_values) = f(x) - E[f(X)]

    Attributes:
        document_path: Path to the analyzed document
        feature_names: Names of document features (sections, wikilinks, etc.)
        shap_values: Shapley values for each feature
        base_value: Expected model output (E[f(X)])
        model_output: Actual model output for this document (f(x))
        augmentation_contribution: Sum of SHAP values for augmentation features
    """

    document_path: Path
    feature_names: list[str]
    shap_values: np.ndarray
    base_value: float
    model_output: float
    augmentation_contribution: float = 0.0

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "document_path": str(self.document_path),
            "feature_names": self.feature_names,
            "shap_values": self.shap_values.tolist(),
            "base_value": self.base_value,
            "model_output": self.model_output,
            "augmentation_contribution": self.augmentation_contribution,
        }


class SHAPAnalyzer:
    """SHAP-based analysis for document augmentation effectiveness.

    ACADEMIC IMPLEMENTATION (Lundberg & Lee 2017):
    Uses KernelSHAP to compute Shapley values for document features,
    specifically measuring the contribution of augmentation sections.

    KernelSHAP approximates Shapley values by:
    1. Sampling feature coalitions from the powerset
    2. Fitting a weighted linear model
    3. Using the linear coefficients as SHAP values

    The feature extraction treats each augmentation type as a binary feature:
    - wikilinks: 1 if present, 0 otherwise
    - action_links: 1 if present, 0 otherwise
    - search_links: 1 if present, 0 otherwise

    Args:
        embedder: Async function to compute document embeddings
        nsamples: Number of coalition samples for KernelSHAP (default: auto)
    """

    def __init__(
        self,
        embedder: EmbedderFn,
        nsamples: str | int = "auto",
    ):
        # SHAP is required at module import - no check needed here
        self.embedder = embedder
        self.nsamples = nsamples

    def _extract_features(self, content: str) -> tuple[np.ndarray, list[str]]:
        """Extract binary features from document content.

        Features represent presence/absence of different content types.

        Args:
            content: Document content

        Returns:
            Tuple of (feature_vector, feature_names)
        """
        import re

        feature_names = [
            "has_wikilinks",
            "has_action_links",
            "has_search_links",
            "has_research_links",
            "has_verify_links",
            "has_augmentation_section",
            "content_length",  # Normalized
        ]

        features = np.zeros(len(feature_names))

        # Wikilinks: [[concept]]
        features[0] = 1.0 if re.search(r"\[\[[^\]]+\]\]", content) else 0.0

        # Action links: [action:type "arg"]
        features[1] = 1.0 if re.search(r'\[action:\w+\s*"[^"]+"\]', content) else 0.0

        # Search links
        features[2] = 1.0 if re.search(r'\[action:search\s*"[^"]+"\]', content) else 0.0

        # Research links
        features[3] = 1.0 if re.search(r'\[action:research\s*"[^"]+"\]', content) else 0.0

        # Verify links
        features[4] = 1.0 if re.search(r'\[action:verify\s*"[^"]+"\]', content) else 0.0

        # Augmentation section
        features[5] = 1.0 if has_augmentation(content) else 0.0

        # Normalized content length (log scale)
        features[6] = np.log1p(len(content)) / 10.0  # Normalize to ~[0, 1]

        return features, feature_names

    def _create_prediction_fn(
        self,
        query: str,
        base_content: str,
        augmentation_parts: dict[str, str],
    ) -> Callable[[np.ndarray], np.ndarray]:
        """Create a prediction function for SHAP analysis.

        The prediction function returns similarity scores for different
        feature combinations (coalitions in game theory terms).

        Args:
            query: Query to compare against
            base_content: Document content without augmentations
            augmentation_parts: Dict of feature_name -> augmentation content

        Returns:
            Function that takes feature mask and returns similarity scores
        """
        import asyncio

        async def async_predict(features: np.ndarray) -> np.ndarray:
            """Async prediction for a batch of feature masks."""
            results = []

            for feature_mask in features:
                # Construct document with enabled features
                content = base_content

                # Add augmentation parts based on mask
                for i, (name, part) in enumerate(augmentation_parts.items()):
                    if i < len(feature_mask) and feature_mask[i] > 0.5:
                        content += f"\n\n{part}"

                # Compute similarity
                sim = await compute_embedding_similarity(query, content, self.embedder)
                results.append(sim)

            return np.array(results)

        def sync_predict(features: np.ndarray) -> np.ndarray:
            """Sync wrapper for SHAP (which expects sync functions)."""
            return asyncio.get_event_loop().run_until_complete(async_predict(features))

        return sync_predict

    async def analyze_document(
        self,
        document_path: Path,
        query: str,
    ) -> SHAPAttribution:
        """Analyze a document's augmentation contribution using SHAP.

        Args:
            document_path: Path to document
            query: Query to evaluate against

        Returns:
            SHAPAttribution with Shapley values

        Raises:
            SHAPNotAvailableError: If SHAP operation fails
        """
        # SHAP is required at module import - import here is for namespace

        content = document_path.read_text()

        # Extract features
        features, feature_names = self._extract_features(content)

        # Separate base content from augmentations
        base_content = strip_augmentation(content)

        # Extract augmentation parts for coalition construction
        augmentation_parts = self._extract_augmentation_parts(content)

        # Create prediction function
        predict_fn = self._create_prediction_fn(query, base_content, augmentation_parts)

        # Create background data (baseline: no augmentations)
        background = np.zeros((1, len(features)))

        # Run KernelSHAP
        explainer = shap.KernelExplainer(predict_fn, background)
        shap_values = explainer.shap_values(features.reshape(1, -1), nsamples=self.nsamples)

        # Extract results
        shap_vals = shap_values[0] if isinstance(shap_values, list) else shap_values.flatten()
        base_value = float(explainer.expected_value)

        # Compute actual model output
        model_output = await compute_embedding_similarity(query, content, self.embedder)

        # Compute augmentation-specific contribution
        # (sum of SHAP values for augmentation-related features)
        aug_indices = [1, 2, 3, 4, 5]  # action_links, search, research, verify, aug_section
        aug_contribution = sum(shap_vals[i] for i in aug_indices if i < len(shap_vals))

        return SHAPAttribution(
            document_path=document_path,
            feature_names=feature_names,
            shap_values=shap_vals,
            base_value=base_value,
            model_output=model_output,
            augmentation_contribution=float(aug_contribution),
        )

    def _extract_augmentation_parts(self, content: str) -> dict[str, str]:
        """Extract individual augmentation sections from content.

        Args:
            content: Full document content

        Returns:
            Dict mapping feature names to augmentation content
        """
        import re

        parts = {}

        # Extract wikilinks
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
        if wikilinks:
            parts["wikilinks"] = " ".join(f"[[{w}]]" for w in wikilinks)

        # Extract action links by type
        for action_type in ["search", "research", "verify", "embed", "web"]:
            matches = re.findall(rf'\[action:{action_type}\s*"([^"]+)"\]', content)
            if matches:
                parts[f"{action_type}_links"] = " ".join(
                    f'[action:{action_type} "{m}"]' for m in matches
                )

        # Extract augmentation section
        aug_match = re.search(
            r"<!-- theta:aug-start -->.*?<!-- theta:aug-end -->",
            content,
            re.DOTALL,
        )
        if aug_match:
            parts["augmentation_section"] = aug_match.group(0)

        return parts

    async def analyze_batch(
        self,
        document_paths: list[Path],
        queries: list[str],
    ) -> list[SHAPAttribution]:
        """Analyze multiple documents with multiple queries.

        Args:
            document_paths: Paths to documents
            queries: Queries to evaluate against

        Returns:
            List of SHAPAttribution results
        """
        results = []

        for doc_path in document_paths:
            if not doc_path.exists():
                continue

            # Use first query as representative (could average across queries)
            if queries:
                try:
                    attribution = await self.analyze_document(doc_path, queries[0])
                    results.append(attribution)
                except Exception as e:
                    logger.warning(f"SHAP analysis failed for {doc_path}: {e}")

        return results


class EffectivenessTracker:
    """Track effectiveness measurements over time.

    Maintains history of measurements for trend analysis and
    Knowledge Gradient belief state updates.
    """

    def __init__(self, history_limit: int = 100):
        self.history: list[EffectivenessResult] = []
        self.history_limit = history_limit
        self._shap_attributions: list[SHAPAttribution] = []

    def add_result(self, result: EffectivenessResult) -> None:
        """Add a measurement result to history."""
        self.history.append(result)

        # Trim history if needed
        if len(self.history) > self.history_limit:
            self.history = self.history[-self.history_limit:]

    def add_shap_attribution(self, attribution: SHAPAttribution) -> None:
        """Add a SHAP attribution result."""
        self._shap_attributions.append(attribution)

        # Trim if needed
        if len(self._shap_attributions) > self.history_limit:
            self._shap_attributions = self._shap_attributions[-self.history_limit:]

    def get_trend(self, window: int = 10) -> dict:
        """Analyze recent trend in effectiveness.

        Args:
            window: Number of recent results to analyze

        Returns:
            Dict with trend statistics
        """
        if not self.history:
            return {"trend": "unknown", "mean_contribution": 0.0}

        recent = self.history[-window:]
        contributions = [r.augmentation_contribution for r in recent]

        mean_contribution = np.mean(contributions)
        std_contribution = np.std(contributions) if len(contributions) > 1 else 0.0

        # Determine trend
        if len(contributions) >= 3:
            first_half = np.mean(contributions[: len(contributions) // 2])
            second_half = np.mean(contributions[len(contributions) // 2:])
            if second_half > first_half + 0.01:
                trend = "improving"
            elif second_half < first_half - 0.01:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "trend": trend,
            "mean_contribution": float(mean_contribution),
            "std_contribution": float(std_contribution),
            "sample_count": len(contributions),
            "positive_rate": sum(1 for c in contributions if c > 0) / len(contributions)
            if contributions
            else 0.0,
        }

    def get_shap_summary(self) -> dict:
        """Get summary of SHAP attributions.

        Returns mean SHAP values across features for interpretability.
        """
        if not self._shap_attributions:
            return {"available": False, "shap_library": True, "reason": "no_attributions_yet"}

        # Aggregate SHAP values across documents
        all_values = np.array([a.shap_values for a in self._shap_attributions])
        mean_values = np.mean(all_values, axis=0)
        std_values = np.std(all_values, axis=0)

        # Get feature names from first attribution
        feature_names = self._shap_attributions[0].feature_names

        # Build summary
        feature_importance = {}
        for i, name in enumerate(feature_names):
            if i < len(mean_values):
                feature_importance[name] = {
                    "mean_shap": float(mean_values[i]),
                    "std_shap": float(std_values[i]),
                    "importance_rank": 0,  # Will be filled below
                }

        # Rank by absolute mean SHAP value
        ranked_features = sorted(
            feature_importance.keys(),
            key=lambda f: abs(feature_importance[f]["mean_shap"]),
            reverse=True,
        )
        for rank, feature in enumerate(ranked_features, 1):
            feature_importance[feature]["importance_rank"] = rank

        return {
            "available": True,
            "shap_library": True,  # SHAP is required - always True if we reach here
            "document_count": len(self._shap_attributions),
            "feature_importance": feature_importance,
            "mean_augmentation_contribution": float(
                np.mean([a.augmentation_contribution for a in self._shap_attributions])
            ),
        }

    def get_stats(self) -> dict:
        """Get tracker statistics."""
        return {
            "history_length": len(self.history),
            "history_limit": self.history_limit,
            "trend": self.get_trend(),
            "shap_summary": self.get_shap_summary(),
        }
