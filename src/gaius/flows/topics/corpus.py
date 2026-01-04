"""Corpus management for incremental topic model building.

Handles tokenization, dictionary updates, and MinIO persistence.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Stopwords for simple tokenization
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "need",
    "that", "which", "who", "whom", "this", "these", "those", "it", "its",
    "we", "they", "he", "she", "i", "you", "what", "where", "when", "how",
    "all", "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "just", "also", "now", "here", "there", "then", "if", "else",
}


@dataclass
class CorpusState:
    """State of an incremental corpus for topic modeling."""

    version_id: str
    document_count: int
    vocabulary_size: int
    model_type: str | None = None
    num_topics: int | None = None  # None for HDP (auto)
    dictionary_path: str | None = None  # MinIO path
    corpus_path: str | None = None  # MinIO path
    model_path: str | None = None  # MinIO path
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "version_id": self.version_id,
            "document_count": self.document_count,
            "vocabulary_size": self.vocabulary_size,
            "model_type": self.model_type,
            "num_topics": self.num_topics,
            "dictionary_path": self.dictionary_path,
            "corpus_path": self.corpus_path,
            "model_path": self.model_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CorpusState":
        """Create from dictionary."""
        return cls(
            version_id=data["version_id"],
            document_count=data["document_count"],
            vocabulary_size=data["vocabulary_size"],
            model_type=data.get("model_type"),
            num_topics=data.get("num_topics"),
            dictionary_path=data.get("dictionary_path"),
            corpus_path=data.get("corpus_path"),
            model_path=data.get("model_path"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )


def tokenize_document(text: str, min_length: int = 3) -> list[str]:
    """Tokenize document with stopword removal and cleaning.

    Args:
        text: Document text to tokenize
        min_length: Minimum token length to keep

    Returns:
        List of cleaned tokens
    """
    # Lowercase
    text = text.lower()

    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)

    # Remove email addresses
    text = re.sub(r"\S+@\S+", "", text)

    # Remove special characters, keep alphanumeric and spaces
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Split into tokens
    tokens = text.split()

    # Filter: remove stopwords, short tokens, and pure numbers
    tokens = [
        t for t in tokens
        if t not in STOPWORDS
        and len(t) >= min_length
        and not t.isdigit()
    ]

    return tokens


def build_corpus_incremental(
    new_tokens: list[str],
    existing_dictionary: Any = None,
) -> tuple[Any, list[tuple[int, int]]]:
    """Add document tokens to corpus incrementally.

    Args:
        new_tokens: Tokenized document
        existing_dictionary: Gensim Dictionary to update (or None for new)

    Returns:
        Tuple of (updated dictionary, BOW representation)
    """
    from gensim import corpora

    if existing_dictionary is None:
        dictionary = corpora.Dictionary()
    else:
        dictionary = existing_dictionary

    # Update dictionary with new tokens
    dictionary.add_documents([new_tokens])

    # Convert to bag-of-words
    bow = dictionary.doc2bow(new_tokens)

    return dictionary, bow


def get_minio_client():
    """Get MinIO client from environment."""
    from minio import Minio

    # Default to port 9010 (devenv) or 9000 (production)
    endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9010")
    access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"

    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


def save_corpus_state(
    state: CorpusState,
    bucket: str = "gaius-models",
    prefix: str = "corpora",
) -> str:
    """Persist corpus state to MinIO.

    Args:
        state: CorpusState to save
        bucket: MinIO bucket name
        prefix: Path prefix in bucket

    Returns:
        S3 path where state was saved
    """
    client = get_minio_client()

    # Ensure bucket exists
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    # Save state as JSON
    s3_path = f"{prefix}/{state.version_id}/state.json"
    state_json = json.dumps(state.to_dict(), indent=2)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(state_json)
        temp_path = f.name

    try:
        client.fput_object(bucket, s3_path, temp_path)
        logger.info(f"Saved corpus state to s3://{bucket}/{s3_path}")
    finally:
        Path(temp_path).unlink(missing_ok=True)

    return f"s3://{bucket}/{s3_path}"


def load_corpus_state(
    bucket: str = "gaius-models",
    prefix: str = "corpora",
    version_id: str | None = None,
) -> CorpusState | None:
    """Load corpus state from MinIO.

    Args:
        bucket: MinIO bucket name
        prefix: Path prefix in bucket
        version_id: Specific version to load (or None for latest)

    Returns:
        CorpusState or None if not found
    """
    client = get_minio_client()

    if not client.bucket_exists(bucket):
        return None

    if version_id:
        # Load specific version
        s3_path = f"{prefix}/{version_id}/state.json"
    else:
        # Find latest version
        objects = list(client.list_objects(bucket, prefix=f"{prefix}/", recursive=True))
        state_objects = [o for o in objects if o.object_name.endswith("state.json")]

        if not state_objects:
            return None

        # Sort by modification time to get latest
        state_objects.sort(key=lambda x: x.last_modified, reverse=True)
        s3_path = state_objects[0].object_name

    try:
        response = client.get_object(bucket, s3_path)
        state_json = response.read().decode("utf-8")
        response.close()
        response.release_conn()

        return CorpusState.from_dict(json.loads(state_json))

    except Exception as e:
        logger.warning(f"Failed to load corpus state: {e}")
        return None


def save_dictionary(
    dictionary: Any,
    bucket: str = "gaius-models",
    prefix: str = "corpora",
    version_id: str = None,
) -> str:
    """Save Gensim dictionary to MinIO.

    Args:
        dictionary: Gensim Dictionary
        bucket: MinIO bucket name
        prefix: Path prefix
        version_id: Version identifier

    Returns:
        S3 path where dictionary was saved
    """
    from datetime import datetime

    client = get_minio_client()

    if version_id is None:
        version_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    s3_path = f"{prefix}/{version_id}/dictionary.dict"

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / "dictionary.dict"
        dictionary.save(str(local_path))
        client.fput_object(bucket, s3_path, str(local_path))

    logger.info(f"Saved dictionary to s3://{bucket}/{s3_path}")
    return f"s3://{bucket}/{s3_path}"


def load_dictionary(
    s3_path: str,
) -> Any:
    """Load Gensim dictionary from MinIO.

    Args:
        s3_path: S3 path (s3://bucket/path)

    Returns:
        Gensim Dictionary
    """
    from gensim import corpora

    # Parse S3 path
    if s3_path.startswith("s3://"):
        s3_path = s3_path[5:]
    bucket, *path_parts = s3_path.split("/", 1)
    object_path = path_parts[0] if path_parts else ""

    client = get_minio_client()

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / "dictionary.dict"
        client.fget_object(bucket, object_path, str(local_path))
        return corpora.Dictionary.load(str(local_path))


def save_corpus(
    corpus: list[list[tuple[int, int]]],
    bucket: str = "gaius-models",
    prefix: str = "corpora",
    version_id: str = None,
) -> str:
    """Save corpus to MinIO in Market Matrix format.

    Args:
        corpus: List of BOW representations
        bucket: MinIO bucket name
        prefix: Path prefix
        version_id: Version identifier

    Returns:
        S3 path where corpus was saved
    """
    from datetime import datetime

    from gensim import corpora

    client = get_minio_client()

    if version_id is None:
        version_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    s3_path = f"{prefix}/{version_id}/corpus.mm"

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / "corpus.mm"
        corpora.MmCorpus.serialize(str(local_path), corpus)
        client.fput_object(bucket, s3_path, str(local_path))

    logger.info(f"Saved corpus to s3://{bucket}/{s3_path}")
    return f"s3://{bucket}/{s3_path}"


def load_corpus(
    s3_path: str,
) -> Any:
    """Load corpus from MinIO.

    Args:
        s3_path: S3 path (s3://bucket/path)

    Returns:
        Gensim MmCorpus
    """
    from gensim import corpora

    # Parse S3 path
    if s3_path.startswith("s3://"):
        s3_path = s3_path[5:]
    bucket, *path_parts = s3_path.split("/", 1)
    object_path = path_parts[0] if path_parts else ""

    client = get_minio_client()

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / "corpus.mm"
        client.fget_object(bucket, object_path, str(local_path))
        return corpora.MmCorpus(str(local_path))
