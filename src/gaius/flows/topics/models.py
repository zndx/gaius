"""Topic model wrappers with consistent interface.

Supports Gensim (LDA, LSA, HDP) and BERTopic with unified output format.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ModelType(str, Enum):
    """Supported topic model types."""

    LDA = "lda"
    LSA = "lsa"
    HDP = "hdp"
    BERTOPIC = "bertopic"


@dataclass
class TopicResult:
    """Result of topic extraction for a document."""

    topics: list[tuple[int, float]]  # (topic_id, weight)
    top_words: dict[int, list[str]]  # topic_id -> top words
    coherence_score: float | None
    model_type: str
    optimal_topics: int | None = None  # HDP/BERTopic discovered count
    embeddings: list[float] | None = None  # Document embedding (BERTopic)


@dataclass
class TopicModel:
    """Wrapper for trained topic model with visualization support."""

    model: Any  # Gensim model or BERTopic instance
    model_type: ModelType
    dictionary: Any | None = None  # Gensim dictionary
    num_topics: int | None = None
    coherence_score: float | None = None

    # BERTopic visualization data (for Metaflow cards)
    topic_info: Any = None  # DataFrame with topic info
    hierarchy_fig: Any = None  # Plotly figure for hierarchy
    barchart_fig: Any = None  # Plotly figure for term importance
    similarity_matrix: Any = None  # Topic similarity matrix

    def get_topic_words(self, topic_id: int, top_n: int = 10) -> list[str]:
        """Get top words for a topic."""
        if self.model_type == ModelType.BERTOPIC:
            topic = self.model.get_topic(topic_id)
            if topic:
                return [word for word, _ in topic[:top_n]]
            return []
        else:
            # Gensim models
            return [word for word, _ in self.model.show_topic(topic_id, top_n)]

    def get_all_topics(self, top_n: int = 10) -> dict[int, list[str]]:
        """Get top words for all topics."""
        result = {}
        if self.model_type == ModelType.BERTOPIC:
            topics = self.model.get_topics()
            for topic_id in topics:
                if topic_id != -1:  # Skip outlier topic
                    result[topic_id] = self.get_topic_words(topic_id, top_n)
        else:
            for i in range(self.num_topics or 10):
                result[i] = self.get_topic_words(i, top_n)
        return result


def train_topic_model(
    documents: list[str],
    model_type: str = "hdp",
    num_topics: int | None = None,
    embedding_model: str = "all-MiniLM-L6-v2",
    random_state: int = 42,
) -> TopicModel:
    """Train a topic model on documents.

    Args:
        documents: List of document texts
        model_type: One of "lda", "lsa", "hdp", "bertopic"
        num_topics: Number of topics (ignored for HDP/BERTopic which auto-discover)
        embedding_model: Sentence transformer model for BERTopic
        random_state: Random seed for reproducibility

    Returns:
        Trained TopicModel instance
    """
    model_type_enum = ModelType(model_type.lower())

    if model_type_enum == ModelType.BERTOPIC:
        return _train_bertopic(documents, embedding_model, random_state)
    else:
        return _train_gensim(documents, model_type_enum, num_topics, random_state)


def _train_bertopic(
    documents: list[str],
    embedding_model: str,
    random_state: int,
) -> TopicModel:
    """Train BERTopic model with visualization figures."""
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from umap import UMAP

    logger.info(f"Training BERTopic with {len(documents)} documents")

    # Use sentence-transformers for embeddings
    embedder = SentenceTransformer(embedding_model)

    # Configure UMAP and HDBSCAN for small corpora
    n_docs = len(documents)

    # UMAP needs n_neighbors <= n_docs - 1, and n_components >= 1
    n_neighbors = min(15, max(2, n_docs - 1))
    n_components = max(2, min(5, n_docs - 1))  # At least 2, at most 5 or n_docs-1
    umap_model = UMAP(
        n_neighbors=n_neighbors,
        n_components=n_components,
        min_dist=0.0,
        metric="cosine",
        random_state=random_state,
    )

    # HDBSCAN with small min_cluster_size for small corpora
    min_cluster_size = max(2, n_docs // 5)  # At least 2, scales with corpus
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,  # Allow single-sample clusters
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )

    # Configure BERTopic with custom UMAP/HDBSCAN
    topic_model = BERTopic(
        embedding_model=embedder,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        verbose=True,
        calculate_probabilities=True,
    )

    # Fit model
    topics, probs = topic_model.fit_transform(documents)

    # Get topic count (excluding outliers at -1)
    unique_topics = set(topics) - {-1}
    num_topics = len(unique_topics)

    logger.info(f"BERTopic discovered {num_topics} topics")

    # Generate visualizations for Metaflow cards
    try:
        topic_info = topic_model.get_topic_info()
        hierarchy_fig = topic_model.visualize_hierarchy()
        barchart_fig = topic_model.visualize_barchart(top_n_topics=min(10, num_topics))
        similarity_matrix = topic_model.visualize_heatmap()
    except Exception as e:
        logger.warning(f"Failed to generate BERTopic visualizations: {e}")
        topic_info = None
        hierarchy_fig = None
        barchart_fig = None
        similarity_matrix = None

    return TopicModel(
        model=topic_model,
        model_type=ModelType.BERTOPIC,
        dictionary=None,
        num_topics=num_topics,
        coherence_score=None,  # BERTopic uses different metrics
        topic_info=topic_info,
        hierarchy_fig=hierarchy_fig,
        barchart_fig=barchart_fig,
        similarity_matrix=similarity_matrix,
    )


def _train_gensim(
    documents: list[str],
    model_type: ModelType,
    num_topics: int | None,
    random_state: int,
) -> TopicModel:
    """Train Gensim model (LDA, LSA, or HDP)."""
    from gensim import corpora, models
    from gensim.models.coherencemodel import CoherenceModel

    from gaius.flows.topics.corpus import tokenize_document

    logger.info(f"Training {model_type.value.upper()} with {len(documents)} documents")

    # Tokenize documents
    texts = [tokenize_document(doc) for doc in documents]

    # Build dictionary and corpus
    dictionary = corpora.Dictionary(texts)
    dictionary.filter_extremes(no_below=2, no_above=0.9)
    corpus = [dictionary.doc2bow(text) for text in texts]

    # Train model
    if model_type == ModelType.LDA:
        num_topics = num_topics or 10
        model = models.LdaModel(
            corpus,
            id2word=dictionary,
            num_topics=num_topics,
            random_state=random_state,
            passes=15,
            alpha="auto",
            eta="auto",
        )
        discovered_topics = num_topics

    elif model_type == ModelType.LSA:
        num_topics = num_topics or 10
        model = models.LsiModel(
            corpus,
            id2word=dictionary,
            num_topics=num_topics,
        )
        discovered_topics = num_topics

    elif model_type == ModelType.HDP:
        # HDP discovers optimal topic count automatically
        model = models.HdpModel(
            corpus,
            id2word=dictionary,
            random_state=random_state,
        )
        # Get number of active topics
        discovered_topics = len(model.get_topics())
        logger.info(f"HDP discovered {discovered_topics} topics")

    else:
        raise ValueError(f"Unknown model type: {model_type}")

    # Calculate coherence score
    try:
        coherence_model = CoherenceModel(
            model=model,
            texts=texts,
            dictionary=dictionary,
            coherence="c_v",
        )
        coherence_score = coherence_model.get_coherence()
        logger.info(f"Coherence score (C_v): {coherence_score:.4f}")
    except Exception as e:
        logger.warning(f"Failed to calculate coherence: {e}")
        coherence_score = None

    return TopicModel(
        model=model,
        model_type=model_type,
        dictionary=dictionary,
        num_topics=discovered_topics,
        coherence_score=coherence_score,
    )


def get_document_topics(
    topic_model: TopicModel,
    document: str,
    top_n: int = 5,
) -> TopicResult:
    """Extract topics for a single document.

    Args:
        topic_model: Trained TopicModel
        document: Document text
        top_n: Number of top topics to return

    Returns:
        TopicResult with topic assignments and metadata
    """
    if topic_model.model_type == ModelType.BERTOPIC:
        return _get_bertopic_topics(topic_model, document, top_n)
    else:
        return _get_gensim_topics(topic_model, document, top_n)


def _get_bertopic_topics(
    topic_model: TopicModel,
    document: str,
    top_n: int,
) -> TopicResult:
    """Get topics from BERTopic model."""
    model = topic_model.model

    # Get topic assignment and probabilities
    topics, probs = model.transform([document])
    topic_id = topics[0]

    # Get topic probabilities if available
    if probs is not None and len(probs) > 0:
        topic_probs = list(enumerate(probs[0]))
        topic_probs.sort(key=lambda x: x[1], reverse=True)
        topics_list = [(tid, float(p)) for tid, p in topic_probs[:top_n] if p > 0.01]
    else:
        # Fallback: just return the assigned topic
        topics_list = [(topic_id, 1.0)]

    # Get top words for each topic
    top_words = {}
    for tid, _ in topics_list:
        if tid != -1:  # Skip outlier topic
            words = topic_model.get_topic_words(tid, 10)
            top_words[tid] = words

    return TopicResult(
        topics=topics_list,
        top_words=top_words,
        coherence_score=topic_model.coherence_score,
        model_type=topic_model.model_type.value,
        optimal_topics=topic_model.num_topics,
    )


def _get_gensim_topics(
    topic_model: TopicModel,
    document: str,
    top_n: int,
) -> TopicResult:
    """Get topics from Gensim model."""
    from gaius.flows.topics.corpus import tokenize_document

    # Gensim models require a dictionary
    if topic_model.dictionary is None:
        raise ValueError("Gensim topic model requires dictionary for BOW conversion")

    # Tokenize and convert to BOW
    tokens = tokenize_document(document)
    bow = topic_model.dictionary.doc2bow(tokens)

    # Get topic distribution
    if topic_model.model_type == ModelType.LSA:
        topic_dist = topic_model.model[bow]
    else:
        topic_dist = topic_model.model.get_document_topics(bow, minimum_probability=0.01)

    # Sort by probability and take top N
    topic_dist = sorted(topic_dist, key=lambda x: abs(x[1]), reverse=True)[:top_n]
    topics_list = [(int(tid), float(prob)) for tid, prob in topic_dist]

    # Get top words for each topic
    top_words = {}
    for tid, _ in topics_list:
        words = topic_model.get_topic_words(tid, 10)
        top_words[tid] = words

    return TopicResult(
        topics=topics_list,
        top_words=top_words,
        coherence_score=topic_model.coherence_score,
        model_type=topic_model.model_type.value,
        optimal_topics=topic_model.num_topics,
    )


def save_topic_model(topic_model: TopicModel, path: Path) -> None:
    """Save topic model to disk."""
    import pickle

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if topic_model.model_type == ModelType.BERTOPIC:
        # BERTopic has its own save method
        topic_model.model.save(str(path / "bertopic_model"))
        # Save metadata separately
        with open(path / "metadata.pkl", "wb") as f:
            pickle.dump(
                {
                    "model_type": topic_model.model_type.value,
                    "num_topics": topic_model.num_topics,
                    "coherence_score": topic_model.coherence_score,
                },
                f,
            )
    else:
        # Gensim models require dictionary
        if topic_model.dictionary is None:
            raise ValueError("Cannot save Gensim model without dictionary")
        topic_model.model.save(str(path / "model"))
        topic_model.dictionary.save(str(path / "dictionary"))
        with open(path / "metadata.pkl", "wb") as f:
            pickle.dump(
                {
                    "model_type": topic_model.model_type.value,
                    "num_topics": topic_model.num_topics,
                    "coherence_score": topic_model.coherence_score,
                },
                f,
            )


def load_topic_model(path: Path) -> TopicModel:
    """Load topic model from disk."""
    import pickle

    from gensim import corpora, models

    path = Path(path)

    with open(path / "metadata.pkl", "rb") as f:
        metadata = pickle.load(f)

    model_type = ModelType(metadata["model_type"])

    if model_type == ModelType.BERTOPIC:
        from bertopic import BERTopic

        model = BERTopic.load(str(path / "bertopic_model"))
        return TopicModel(
            model=model,
            model_type=model_type,
            dictionary=None,
            num_topics=metadata["num_topics"],
            coherence_score=metadata["coherence_score"],
        )
    else:
        # Load Gensim model
        if model_type == ModelType.LDA:
            model = models.LdaModel.load(str(path / "model"))
        elif model_type == ModelType.LSA:
            model = models.LsiModel.load(str(path / "model"))
        elif model_type == ModelType.HDP:
            model = models.HdpModel.load(str(path / "model"))
        else:
            raise ValueError(f"Unknown model type: {model_type}")

        dictionary = corpora.Dictionary.load(str(path / "dictionary"))

        return TopicModel(
            model=model,
            model_type=model_type,
            dictionary=dictionary,
            num_topics=metadata["num_topics"],
            coherence_score=metadata["coherence_score"],
        )
