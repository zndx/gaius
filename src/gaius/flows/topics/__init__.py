"""Topic modeling utilities for Gaius flows.

Provides LDA, LSA, HDP (Gensim) and BERTopic for document analysis
with incremental corpus building and MinIO persistence.
"""

from gaius.flows.topics.corpus import (
    CorpusState,
    build_corpus_incremental,
    load_corpus_state,
    save_corpus_state,
    tokenize_document,
)
from gaius.flows.topics.models import (
    ModelType,
    TopicModel,
    TopicResult,
    get_document_topics,
    load_topic_model,
    save_topic_model,
    train_topic_model,
)
from gaius.flows.topics.scoring import (
    PaperScore,
    ScoringRubric,
    filter_by_score,
    get_default_rubric,
    load_rubric,
    rank_papers,
    score_batch,
    score_paper,
)

__all__ = [
    # Corpus
    "CorpusState",
    "build_corpus_incremental",
    "load_corpus_state",
    "save_corpus_state",
    "tokenize_document",
    # Models
    "ModelType",
    "TopicModel",
    "TopicResult",
    "get_document_topics",
    "load_topic_model",
    "save_topic_model",
    "train_topic_model",
    # Scoring
    "PaperScore",
    "ScoringRubric",
    "filter_by_score",
    "get_default_rubric",
    "load_rubric",
    "rank_papers",
    "score_batch",
    "score_paper",
]
