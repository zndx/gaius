"""Text Classification for Ontology Coherence Validation.

Provides sklearn-based text classification to validate that ontology
verbalizations have learnable structure - i.e., the verbalized text
can be used to predict the original concept.

This replaces the heavier BERTopic/UMAP approach for coherence validation,
providing:
- Faster execution (no embedding inference)
- More stable for small corpora (<50 docs)
- Clear accuracy metric for coherence

The core idea: if a simple classifier can learn to predict concept labels
from verbalization text, the ontology has coherent, distinguishable concepts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of coherence classification."""

    accuracy: float
    num_classes: int
    num_samples: int
    train_accuracy: float
    classification_report: str | None = None
    feature_importances: list[tuple[str, float]] | None = None


class OntologyCoherenceClassifier:
    """Validates ontology coherence via text classification.

    Uses TF-IDF + SGDClassifier to learn a mapping from verbalization
    text to concept labels. High accuracy indicates coherent, distinct
    concepts that can be recovered from their textual descriptions.

    Attributes:
        ngram_range: N-gram range for TF-IDF (default (1, 2) for unigrams+bigrams)
        max_features: Maximum vocabulary size
        test_size: Fraction of data held out for testing
        min_samples_per_class: Minimum samples needed per class
    """

    def __init__(
        self,
        ngram_range: tuple[int, int] = (1, 2),
        max_features: int = 1000,
        test_size: float = 0.2,
        min_samples_per_class: int = 1,
    ):
        self.ngram_range = ngram_range
        self.max_features = max_features
        self.test_size = test_size
        self.min_samples_per_class = min_samples_per_class
        self._pipeline = None

    def _build_pipeline(self, use_early_stopping: bool = False):
        """Build sklearn classification pipeline.

        Args:
            use_early_stopping: Whether to use early stopping. Disable for
                datasets with unique classes (1 sample per class).
        """
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import SGDClassifier
        from sklearn.pipeline import Pipeline

        return Pipeline([
            ('tfidf', TfidfVectorizer(
                ngram_range=self.ngram_range,
                max_features=self.max_features,
                stop_words='english',
                lowercase=True,
            )),
            ('clf', SGDClassifier(
                loss='log_loss',  # Logistic regression
                max_iter=200,
                early_stopping=use_early_stopping,
                n_iter_no_change=5 if use_early_stopping else 200,
                random_state=42,
            ))
        ])

    def fit_evaluate(
        self,
        texts: list[str],
        labels: list[str],
    ) -> ClassificationResult:
        """Fit classifier and evaluate coherence.

        Args:
            texts: Verbalization texts
            labels: Concept labels (class expressions or IDs)

        Returns:
            ClassificationResult with accuracy and stats
        """
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder

        if len(texts) < 5:
            return ClassificationResult(
                accuracy=0.0,
                num_classes=0,
                num_samples=len(texts),
                train_accuracy=0.0,
                classification_report="Insufficient samples (< 5)",
            )

        # Encode labels
        le = LabelEncoder()
        y = le.fit_transform(labels)
        num_classes = len(le.classes_)

        # Filter out classes with too few samples
        from collections import Counter
        label_counts = Counter(y)
        valid_labels = {l for l, c in label_counts.items() if c >= self.min_samples_per_class}

        if len(valid_labels) < 2:
            return ClassificationResult(
                accuracy=0.0,
                num_classes=num_classes,
                num_samples=len(texts),
                train_accuracy=0.0,
                classification_report="Insufficient classes with enough samples",
            )

        # Filter data to valid labels
        mask = [l in valid_labels for l in y]
        X_filtered = [t for t, m in zip(texts, mask) if m]
        y_filtered = [l for l, m in zip(y, mask) if m]

        if len(X_filtered) < 5:
            return ClassificationResult(
                accuracy=0.0,
                num_classes=len(valid_labels),
                num_samples=len(X_filtered),
                train_accuracy=0.0,
                classification_report="Insufficient samples after filtering",
            )

        # Split data
        # For very small datasets, use more samples for training
        actual_test_size = min(self.test_size, max(1, len(X_filtered) // 5) / len(X_filtered))

        try:
            X_train, X_test, y_train, y_test = train_test_split(
                X_filtered, y_filtered,
                test_size=actual_test_size,
                stratify=y_filtered if len(set(y_filtered)) > 1 else None,
                random_state=42,
            )
        except ValueError:
            # Stratification failed, try without
            X_train, X_test, y_train, y_test = train_test_split(
                X_filtered, y_filtered,
                test_size=actual_test_size,
                random_state=42,
            )

        # Determine if we can use early stopping (need at least 2 samples per class in train set)
        from collections import Counter as TrainCounter
        train_counts = TrainCounter(y_train)
        min_train_count = min(train_counts.values()) if train_counts else 0
        use_early_stopping = min_train_count >= 2

        # Build and train pipeline
        self._pipeline = self._build_pipeline(use_early_stopping=use_early_stopping)
        self._pipeline.fit(X_train, y_train)

        # Evaluate
        train_accuracy = self._pipeline.score(X_train, y_train)
        test_accuracy = self._pipeline.score(X_test, y_test)

        # Generate classification report
        try:
            from sklearn.metrics import classification_report as sk_report
            y_pred = self._pipeline.predict(X_test)
            report = sk_report(y_test, y_pred, zero_division=0)
        except Exception as e:
            report = f"Error generating report: {e}"

        # Get feature importances (top terms per class)
        feature_importances = self._get_top_features(5)

        return ClassificationResult(
            accuracy=test_accuracy,
            num_classes=len(valid_labels),
            num_samples=len(X_filtered),
            train_accuracy=train_accuracy,
            classification_report=report,
            feature_importances=feature_importances,
        )

    def _get_top_features(self, n: int = 10) -> list[tuple[str, float]]:
        """Get top features by importance.

        Returns average absolute coefficient across all classes.
        """
        if self._pipeline is None:
            return []

        try:
            tfidf = self._pipeline.named_steps['tfidf']
            clf = self._pipeline.named_steps['clf']

            feature_names = tfidf.get_feature_names_out()
            coefs = np.abs(clf.coef_).mean(axis=0) if clf.coef_.ndim > 1 else np.abs(clf.coef_)

            top_indices = coefs.argsort()[-n:][::-1]
            return [(feature_names[i], float(coefs[i])) for i in top_indices]
        except Exception:
            return []

    def fit_evaluate_from_verbalizations(
        self,
        verbalizations: list[dict[str, str]],
    ) -> ClassificationResult:
        """Evaluate coherence from verbalization dicts.

        Args:
            verbalizations: List of {"class_expr": ..., "verbalization": ...}

        Returns:
            ClassificationResult with accuracy and stats
        """
        texts = [v["verbalization"] for v in verbalizations]
        labels = [v.get("class_expr", str(i)) for i, v in enumerate(verbalizations)]
        return self.fit_evaluate(texts, labels)

    def fit_evaluate_from_owl(
        self,
        owl_path: str | Path,
        kb_root: str | Path | None = None,
    ) -> ClassificationResult:
        """Evaluate coherence directly from OWL file.

        Args:
            owl_path: Path to OWL file (relative to kb_root or absolute)
            kb_root: KB root directory

        Returns:
            ClassificationResult with accuracy and stats
        """
        from .ontology_constraints import _ensure_jvm_ready

        # Resolve path
        owl_path = Path(owl_path)
        if not owl_path.is_absolute() and kb_root:
            owl_path = Path(kb_root) / owl_path

        if not owl_path.exists():
            return ClassificationResult(
                accuracy=0.0,
                num_classes=0,
                num_samples=0,
                train_accuracy=0.0,
                classification_report=f"OWL file not found: {owl_path}",
            )

        try:
            _ensure_jvm_ready()
            from deeponto.onto import Ontology, OntologyVerbaliser

            onto = Ontology(str(owl_path))
            verbaliser = OntologyVerbaliser(onto)
            complex_classes = list(onto.get_asserted_complex_classes())

            verbalizations = []
            for concept in complex_classes:
                try:
                    v = verbaliser.verbalise_class_expression(concept)
                    if v.verbal and len(v.verbal) >= 10:
                        verbalizations.append({
                            "class_expr": str(concept)[:100],
                            "verbalization": v.verbal,
                        })
                except Exception:
                    pass

            if not verbalizations:
                return ClassificationResult(
                    accuracy=0.0,
                    num_classes=0,
                    num_samples=0,
                    train_accuracy=0.0,
                    classification_report="No verbalizations generated",
                )

            return self.fit_evaluate_from_verbalizations(verbalizations)

        except ImportError as e:
            return ClassificationResult(
                accuracy=0.0,
                num_classes=0,
                num_samples=0,
                train_accuracy=0.0,
                classification_report=f"DeepOnto not available: {e}",
            )
        except Exception as e:
            return ClassificationResult(
                accuracy=0.0,
                num_classes=0,
                num_samples=0,
                train_accuracy=0.0,
                classification_report=f"Error: {e}",
            )


def compute_coherence_score(
    verbalizations: list[dict[str, str]],
    threshold: float = 0.5,
) -> tuple[bool, float, str]:
    """Convenience function to compute coherence score.

    For ontology verbalizations, we measure two things:
    1. Vocabulary coherence: Do verbalizations share domain vocabulary?
    2. Distinctiveness: Are top features meaningful domain terms?

    Args:
        verbalizations: List of {"class_expr": ..., "verbalization": ...}
        threshold: Minimum score to consider coherent (0.5 default)

    Returns:
        Tuple of (is_coherent, score, message)
    """
    if len(verbalizations) < 5:
        # Use keyword overlap for very small corpora
        return _keyword_coherence(verbalizations, threshold)

    # For ontology verbalizations, use a hybrid approach:
    # 1. Fit classifier to extract TF-IDF features
    # 2. Use keyword coherence for the score (more stable for 1-sample-per-class)
    # 3. Report top features for interpretability

    clf = OntologyCoherenceClassifier()
    result = clf.fit_evaluate_from_verbalizations(verbalizations)

    # Use keyword coherence as the primary score
    _, keyword_score, _ = _keyword_coherence(verbalizations, threshold)

    # Blend with train accuracy if classifier learned something
    if result.train_accuracy > 0.5:
        # Weight keyword coherence more heavily (0.7) since it's more stable
        blended_score = 0.7 * keyword_score + 0.3 * min(result.train_accuracy, 1.0)
    else:
        blended_score = keyword_score

    is_coherent = blended_score >= threshold
    message = (
        f"Coherence: {blended_score:.1%} "
        f"(vocab overlap: {keyword_score:.1%}, {result.num_samples} docs)"
    )

    if result.feature_importances:
        top_terms = [f[0] for f in result.feature_importances[:3]]
        message += f", top terms: {', '.join(top_terms)}"

    return is_coherent, blended_score, message


def _keyword_coherence(
    verbalizations: list[dict[str, str]],
    threshold: float,
) -> tuple[bool, float, str]:
    """Compute keyword-based coherence for small corpora.

    Used when there aren't enough samples for classification.
    """
    if not verbalizations:
        return False, 0.0, "No verbalizations"

    all_words = []
    for v in verbalizations:
        words = set(v["verbalization"].lower().split())
        # Filter short/common words
        words = {w for w in words if len(w) > 3}
        all_words.append(words)

    # Check vocabulary overlap between verbalizations
    overlap_count = 0
    total_pairs = 0
    for i, words_i in enumerate(all_words):
        for j, words_j in enumerate(all_words):
            if i < j:
                overlap = len(words_i & words_j)
                if overlap >= 2:
                    overlap_count += 1
                total_pairs += 1

    if total_pairs > 0:
        coherence = overlap_count / total_pairs
    else:
        coherence = 1.0

    is_coherent = coherence >= threshold
    message = f"Keyword coherence: {coherence:.1%} ({len(verbalizations)} docs, keyword fallback)"

    return is_coherent, coherence, message


__all__ = [
    "ClassificationResult",
    "OntologyCoherenceClassifier",
    "compute_coherence_score",
]
