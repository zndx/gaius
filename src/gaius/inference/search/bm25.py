"""BM25 search over KB markdown files.

Uses bm25s for fast lexical search with stemming support.
Index is built on-demand and cached in memory.

Usage:
    kb_search = KBSearch(kb_root=Path("build/dev"))
    kb_search.build_index()  # Or rebuild_index() to force refresh

    results = kb_search.search("distributed consensus", top_k=10)
    for result in results:
        print(f"{result.path}: {result.score:.3f}")
        print(f"  {result.snippet}")
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import bm25s
import Stemmer


@dataclass
class KBDocument:
    """A KB document with metadata."""

    path: str  # Relative path from KB root
    title: str
    content: str
    metadata: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """Combined title and content for indexing."""
        return f"{self.title}\n\n{self.content}"


@dataclass
class KBSearchResult:
    """A search result with citation info."""

    path: str  # KB path for citation
    title: str
    score: float
    snippet: str  # Relevant excerpt
    match_pattern: str | None = None  # Regex to locate match
    line_number: int | None = None  # Line where match found


class KBSearch:
    """BM25 search engine for KB markdown files.

    Indexes all .md files under allowed KB directories.
    Supports stemming via PyStemmer for better recall.
    """

    ALLOWED_DIRS = ("archive", "current", "scratch")

    def __init__(
        self,
        kb_root: Path | str | None = None,
        stemmer_lang: str = "english",
    ):
        """Initialize KB search.

        Args:
            kb_root: Root of KB directory (default: GAIUS_KB_ROOT or build/dev)
            stemmer_lang: Stemmer language for bm25s
        """
        if kb_root is None:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        self.kb_root = Path(kb_root)

        # BM25 components
        self.stemmer = Stemmer.Stemmer(stemmer_lang)
        self.retriever: bm25s.BM25 | None = None
        self.documents: list[KBDocument] = []
        self._doc_paths: list[str] = []  # For fast lookup by index

    def build_index(self, force: bool = False) -> int:
        """Build or rebuild the BM25 index.

        Args:
            force: Rebuild even if index exists

        Returns:
            Number of documents indexed
        """
        if self.retriever is not None and not force:
            return len(self.documents)

        self.documents = list(self._load_documents())
        self._doc_paths = [doc.path for doc in self.documents]

        if not self.documents:
            return 0

        # Tokenize with stemming (suppress progress bars)
        corpus = [doc.full_text for doc in self.documents]
        corpus_tokens = bm25s.tokenize(
            corpus,
            stemmer=self.stemmer,
            stopwords="english",
            show_progress=False,
        )

        # Build BM25 index
        self.retriever = bm25s.BM25()
        self.retriever.index(corpus_tokens, show_progress=False)

        return len(self.documents)

    def rebuild_index(self) -> int:
        """Force rebuild of the index."""
        return self.build_index(force=True)

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[KBSearchResult]:
        """Search KB for query.

        Args:
            query: Search query
            top_k: Maximum results to return
            min_score: Minimum BM25 score threshold

        Returns:
            List of KBSearchResult sorted by score descending
        """
        if self.retriever is None:
            self.build_index()

        if not self.documents:
            return []

        # Tokenize query with same stemmer
        query_tokens = bm25s.tokenize(
            [query],
            stemmer=self.stemmer,
            stopwords="english",
            show_progress=False,
        )

        # Retrieve
        results, scores = self.retriever.retrieve(
            query_tokens,
            corpus=self.documents,
            k=min(top_k, len(self.documents)),
            show_progress=False,
        )

        # Build result objects
        search_results = []
        for doc, score in zip(results[0], scores[0]):
            if score < min_score:
                continue

            # Find best matching line for snippet and citation
            snippet, line_num, pattern = self._find_best_match(doc.content, query)

            search_results.append(KBSearchResult(
                path=doc.path,
                title=doc.title,
                score=float(score),
                snippet=snippet,
                match_pattern=pattern,
                line_number=line_num,
            ))

        return search_results

    def _load_documents(self) -> Iterator[KBDocument]:
        """Load all KB markdown documents."""
        for dir_name in self.ALLOWED_DIRS:
            dir_path = self.kb_root / dir_name
            if not dir_path.exists():
                continue

            for md_file in dir_path.rglob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    rel_path = str(md_file.relative_to(self.kb_root))

                    # Extract title from first heading or filename
                    title = self._extract_title(content, md_file.stem)

                    yield KBDocument(
                        path=rel_path,
                        title=title,
                        content=content,
                    )
                except Exception:
                    # Skip files that can't be read
                    continue

    def _extract_title(self, content: str, fallback: str) -> str:
        """Extract title from markdown heading."""
        for line in content.split("\n")[:10]:
            if line.startswith("# "):
                return line[2:].strip()
        return fallback.replace("-", " ").replace("_", " ").title()

    def _find_best_match(
        self,
        content: str,
        query: str,
    ) -> tuple[str, int | None, str | None]:
        """Find the best matching line for snippet and citation.

        Returns:
            (snippet, line_number, regex_pattern)
        """
        lines = content.split("\n")
        query_terms = query.lower().split()

        best_line = None
        best_line_num = None
        best_score = 0

        for i, line in enumerate(lines, 1):
            line_lower = line.lower()
            # Score by number of query terms present
            score = sum(1 for term in query_terms if term in line_lower)
            if score > best_score and len(line.strip()) > 10:
                best_score = score
                best_line = line.strip()
                best_line_num = i

        if best_line:
            # Create regex pattern for citation
            # Escape special chars and use first significant words
            words = [w for w in best_line.split()[:6] if len(w) > 2]
            if words:
                pattern = r".*".join(re.escape(w) for w in words[:3])
            else:
                pattern = None

            # Truncate snippet
            snippet = best_line[:200] + "..." if len(best_line) > 200 else best_line
            return snippet, best_line_num, pattern

        # Fallback to first non-empty line
        for i, line in enumerate(lines, 1):
            if line.strip() and not line.startswith("#"):
                snippet = line.strip()[:200]
                return snippet, i, None

        return content[:200] + "...", 1, None

    def get_document(self, path: str) -> KBDocument | None:
        """Get a document by path."""
        for doc in self.documents:
            if doc.path == path:
                return doc
        return None

    @property
    def index_size(self) -> int:
        """Number of documents in index."""
        return len(self.documents)


# Module-level singleton for convenience
_kb_search: KBSearch | None = None


def get_kb_search(kb_root: Path | str | None = None) -> KBSearch:
    """Get or create KB search singleton."""
    global _kb_search
    if _kb_search is None:
        _kb_search = KBSearch(kb_root)
    return _kb_search
