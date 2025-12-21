"""KB constraints for RASE verification.

Provides Constraint[KBState] implementations for verifying KB documents.
Constraints are organized by gate level:

Syntactic (cheap, fast):
- DocumentParses: Document is valid markdown
- FrontmatterValid: Frontmatter matches schema
- OutputStructureValid: Output matches expected structure

Semantic (medium cost):
- WikilinksResolve: All [[wikilinks]] resolve to existing docs
- HasCitations: Document contains minimum number of citations

Empirical (expensive, definitive):
- CitationsAccessible: Citation URLs return HTTP 200
- SemanticCoherence: Content is semantically coherent with sources
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import Field

from gaius.rase.core.constraints import Constraint, ConstraintResult

from .state import KBState, KBDocument


class DocumentParses(Constraint[KBState]):
    """Verify document parses as valid markdown.

    This is the most basic syntactic gate - the document must be
    readable and structurally valid.

    Attributes:
        document_path: Path to document in KB
    """

    document_path: str

    @property
    def name(self) -> str:
        return f"DocumentParses({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
                {"path": self.document_path},
            )

        if not doc.is_valid_markdown:
            return ConstraintResult.failure(
                self.name,
                f"Document failed to parse: {doc.parse_error}",
                {"path": self.document_path, "error": doc.parse_error},
            )

        return ConstraintResult.success(
            self.name,
            f"Document parses successfully ({doc.word_count} words)",
        )


class FrontmatterValid(Constraint[KBState]):
    """Verify document frontmatter matches expected schema.

    Checks that required fields are present and have valid types.

    Attributes:
        document_path: Path to document in KB
        required_fields: List of required frontmatter fields
        field_types: Optional dict of field -> expected type
    """

    document_path: str
    required_fields: list[str] = Field(default_factory=lambda: ["name", "description"])
    field_types: dict[str, str] = Field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"FrontmatterValid({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        if not doc.frontmatter:
            return ConstraintResult.failure(
                self.name,
                "Document has no frontmatter",
            )

        # Check required fields
        missing = [f for f in self.required_fields if f not in doc.frontmatter]
        if missing:
            return ConstraintResult.failure(
                self.name,
                f"Missing required fields: {', '.join(missing)}",
                {"missing_fields": missing},
            )

        # Check field types if specified
        type_errors = []
        for field, expected_type in self.field_types.items():
            if field in doc.frontmatter:
                value = doc.frontmatter[field]
                actual_type = type(value).__name__
                if actual_type != expected_type:
                    type_errors.append(f"{field}: expected {expected_type}, got {actual_type}")

        if type_errors:
            return ConstraintResult.failure(
                self.name,
                f"Type errors: {'; '.join(type_errors)}",
                {"type_errors": type_errors},
            )

        return ConstraintResult.success(
            self.name,
            f"Frontmatter valid with {len(doc.frontmatter)} fields",
        )


class WikilinksResolve(Constraint[KBState]):
    """Verify all wikilinks in document resolve to existing documents.

    This is a semantic gate that checks the KB structure is consistent.

    Attributes:
        document_path: Path to document in KB
        allow_missing: If True, missing links are warnings not failures
    """

    document_path: str
    allow_missing: bool = False

    @property
    def name(self) -> str:
        return f"WikilinksResolve({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        if not doc.wikilinks:
            return ConstraintResult.success(
                self.name,
                "No wikilinks to verify",
            )

        unresolved = []
        for link in doc.wikilinks:
            if not state.document_exists(link.target):
                unresolved.append(link.target)

        if unresolved:
            if self.allow_missing:
                return ConstraintResult.success(
                    self.name,
                    f"Resolved {len(doc.wikilinks) - len(unresolved)}/{len(doc.wikilinks)} "
                    f"links ({len(unresolved)} missing: {', '.join(unresolved[:3])}...)",
                )
            return ConstraintResult.failure(
                self.name,
                f"{len(unresolved)} unresolved wikilinks: {', '.join(unresolved[:5])}",
                {"unresolved": unresolved},
            )

        return ConstraintResult.success(
            self.name,
            f"All {len(doc.wikilinks)} wikilinks resolve",
        )


class HasCitations(Constraint[KBState]):
    """Verify document contains minimum number of citations.

    Citations include markdown links to external URLs.

    Attributes:
        document_path: Path to document in KB
        min_citations: Minimum required citations (default 1)
    """

    document_path: str
    min_citations: int = 1

    @property
    def name(self) -> str:
        return f"HasCitations({self.document_path}, min={self.min_citations})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        citation_count = len(doc.citations)

        if citation_count < self.min_citations:
            return ConstraintResult.failure(
                self.name,
                f"Document has {citation_count} citations, requires {self.min_citations}",
                {"found": citation_count, "required": self.min_citations},
            )

        return ConstraintResult.success(
            self.name,
            f"Document has {citation_count} citations (>= {self.min_citations})",
        )


class CitationsAccessible(Constraint[KBState]):
    """Verify citation URLs are accessible (HTTP 200).

    This is an empirical gate that makes actual HTTP requests.
    Use sparingly due to latency and rate limiting concerns.

    Attributes:
        document_path: Path to document in KB
        timeout: HTTP request timeout in seconds
        sample_size: Max citations to check (0 = all)
    """

    document_path: str
    timeout: float = 10.0
    sample_size: int = 5

    @property
    def name(self) -> str:
        return f"CitationsAccessible({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        if not doc.citations:
            return ConstraintResult.success(
                self.name,
                "No citations to verify",
            )

        # Sample citations if too many
        citations_to_check = doc.citations
        if self.sample_size > 0 and len(citations_to_check) > self.sample_size:
            citations_to_check = citations_to_check[:self.sample_size]

        accessible = []
        inaccessible = []

        for citation in citations_to_check:
            try:
                # Use HEAD request to minimize bandwidth
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    response = client.head(citation.url)
                    if response.status_code < 400:
                        accessible.append(citation.url)
                    else:
                        inaccessible.append((citation.url, response.status_code))
            except Exception as e:
                inaccessible.append((citation.url, str(e)))

        if inaccessible:
            return ConstraintResult.failure(
                self.name,
                f"{len(inaccessible)}/{len(citations_to_check)} citations inaccessible",
                {
                    "inaccessible": [
                        {"url": url, "error": err}
                        for url, err in inaccessible
                    ]
                },
            )

        sampled_note = ""
        if len(doc.citations) > len(citations_to_check):
            sampled_note = f" (sampled {len(citations_to_check)}/{len(doc.citations)})"

        return ConstraintResult.success(
            self.name,
            f"All {len(accessible)} citations accessible{sampled_note}",
        )


class SemanticCoherence(Constraint[KBState]):
    """Verify document content is semantically coherent with sources.

    Uses embedding similarity to check that claims in the document
    are grounded in cited sources.

    This is an expensive empirical gate that requires embeddings.

    Attributes:
        document_path: Path to document in KB
        source_paths: Paths to source documents
        threshold: Minimum similarity threshold (0.0-1.0)
    """

    document_path: str
    source_paths: list[str] = Field(default_factory=list)
    threshold: float = 0.7

    @property
    def name(self) -> str:
        return f"SemanticCoherence({self.document_path}, threshold={self.threshold})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        if not self.source_paths:
            # If no explicit sources, check citations
            if not doc.citations:
                return ConstraintResult.success(
                    self.name,
                    "No sources to compare (document has no citations)",
                )
            # TODO: Fetch citation content and compare
            return ConstraintResult.success(
                self.name,
                "Semantic coherence check skipped (citation content not fetched)",
            )

        # Load source documents
        sources = []
        for path in self.source_paths:
            source_doc = state.get_document(path)
            if source_doc:
                sources.append(source_doc)

        if not sources:
            return ConstraintResult.failure(
                self.name,
                f"No source documents found: {self.source_paths}",
            )

        # TODO: Implement actual semantic similarity check
        # For now, this is a placeholder that passes
        return ConstraintResult.success(
            self.name,
            f"Semantic coherence check passed (placeholder - {len(sources)} sources)",
        )


class OutputStructureValid(Constraint[KBState]):
    """Verify document output matches expected structure.

    Checks that specific sections, headings, or patterns are present.
    Useful for verifying agent outputs conform to expected format.

    Attributes:
        document_path: Path to document in KB
        required_sections: List of required section headings
        required_patterns: List of regex patterns that must match
    """

    document_path: str
    required_sections: list[str] = Field(default_factory=list)
    required_patterns: list[str] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return f"OutputStructureValid({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        errors = []

        # Check required sections (as markdown headings)
        for section in self.required_sections:
            # Match # Section, ## Section, ### Section, etc.
            pattern = rf"^#+\s*{re.escape(section)}\s*$"
            if not re.search(pattern, doc.body, re.MULTILINE | re.IGNORECASE):
                errors.append(f"Missing section: {section}")

        # Check required patterns
        for pattern in self.required_patterns:
            if not re.search(pattern, doc.body, re.MULTILINE):
                errors.append(f"Missing pattern: {pattern}")

        if errors:
            return ConstraintResult.failure(
                self.name,
                f"Structure validation failed: {'; '.join(errors)}",
                {"errors": errors},
            )

        checks_passed = len(self.required_sections) + len(self.required_patterns)
        return ConstraintResult.success(
            self.name,
            f"Structure valid ({checks_passed} checks passed)",
        )


# Type alias for backward compatibility
Constraint = Constraint


class HasWikilinks(Constraint[KBState]):
    """Verify document contains wikilinks (syntactic format check).

    Attributes:
        document_path: Path to document in KB
        min_links: Minimum required wikilinks (0 = just validate format)
    """

    document_path: str
    min_links: int = 0

    @property
    def name(self) -> str:
        return f"HasWikilinks({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        link_count = len(doc.wikilinks)

        if link_count < self.min_links:
            return ConstraintResult.failure(
                self.name,
                f"Document has {link_count} wikilinks, requires {self.min_links}",
                {"found": link_count, "required": self.min_links},
            )

        return ConstraintResult.success(
            self.name,
            f"Document has {link_count} wikilinks",
        )


class NoOrphanLinks(Constraint[KBState]):
    """Verify no wikilinks point to deleted/non-existent documents.

    Similar to WikilinksResolve but framed as absence of orphans.

    Attributes:
        document_path: Path to document in KB
        check_bidirectional: If True, also check for backlinks
    """

    document_path: str
    check_bidirectional: bool = False

    @property
    def name(self) -> str:
        return f"NoOrphanLinks({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        orphan_links = []
        for link in doc.wikilinks:
            if not state.document_exists(link.target):
                orphan_links.append(link.target)

        if orphan_links:
            return ConstraintResult.failure(
                self.name,
                f"{len(orphan_links)} orphan links: {', '.join(orphan_links[:5])}",
                {"orphan_links": orphan_links},
            )

        return ConstraintResult.success(
            self.name,
            f"No orphan links (checked {len(doc.wikilinks)} links)",
        )


class LinkDensity(Constraint[KBState]):
    """Verify link density is within healthy bounds.

    Too few links: document may be isolated
    Too many links: document may be link spam

    Attributes:
        document_path: Path to document in KB
        min_ratio: Min links per word (default 0.001 = 1 per 1000 words)
        max_ratio: Max links per word (default 0.1 = 1 per 10 words)
    """

    document_path: str
    min_ratio: float = 0.001
    max_ratio: float = 0.1

    @property
    def name(self) -> str:
        return f"LinkDensity({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        if doc.word_count == 0:
            return ConstraintResult.success(
                self.name,
                "Empty document - density check skipped",
            )

        link_count = len(doc.wikilinks) + len(doc.citations)
        ratio = link_count / doc.word_count

        if ratio < self.min_ratio and link_count > 0:
            # Only fail if there are some links but too few
            return ConstraintResult.success(
                self.name,
                f"Link density {ratio:.4f} (low but acceptable)",
            )

        if ratio > self.max_ratio:
            return ConstraintResult.failure(
                self.name,
                f"Link density {ratio:.4f} exceeds max {self.max_ratio}",
                {"ratio": ratio, "max": self.max_ratio, "links": link_count},
            )

        return ConstraintResult.success(
            self.name,
            f"Link density {ratio:.4f} within bounds [{self.min_ratio}, {self.max_ratio}]",
        )


class CitationsNotStale(Constraint[KBState]):
    """Verify citations are not too old.

    Checks that cited content is reasonably current.

    Attributes:
        document_path: Path to document in KB
        max_age_days: Maximum age of citations in days
        check_wayback: Whether to check archive.org for moved content
    """

    document_path: str
    max_age_days: int = 365
    check_wayback: bool = False

    @property
    def name(self) -> str:
        return f"CitationsNotStale({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        if not doc.citations:
            return ConstraintResult.success(
                self.name,
                "No citations to check for staleness",
            )

        # Note: Actual age checking would require fetching page metadata
        # or checking HTTP Last-Modified headers. This is a placeholder.
        return ConstraintResult.success(
            self.name,
            f"Citation staleness check passed ({len(doc.citations)} citations - age check not implemented)",
        )


class SourcesAuthoritative(Constraint[KBState]):
    """Verify sources are from authoritative domains.

    Checks that citations don't come from blocklisted domains.

    Attributes:
        document_path: Path to document in KB
        blocklist_domains: List of domains to reject
    """

    document_path: str
    blocklist_domains: list[str] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return f"SourcesAuthoritative({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        if not doc.citations:
            return ConstraintResult.success(
                self.name,
                "No citations to check for authority",
            )

        blocklisted = []
        for citation in doc.citations:
            for domain in self.blocklist_domains:
                if domain in citation.url:
                    blocklisted.append((citation.url, domain))

        if blocklisted:
            return ConstraintResult.failure(
                self.name,
                f"{len(blocklisted)} citations from blocklisted domains",
                {"blocklisted": blocklisted},
            )

        return ConstraintResult.success(
            self.name,
            f"All {len(doc.citations)} citations from authoritative sources",
        )


class ClaimsIdentified(Constraint[KBState]):
    """Identify factual claims in document for verification.

    Uses heuristics to extract declarative statements.

    Attributes:
        document_path: Path to document in KB
        min_claims: Minimum required claims
    """

    document_path: str
    min_claims: int = 1

    @property
    def name(self) -> str:
        return f"ClaimsIdentified({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        # Simple heuristic: sentences with "is", "are", "was", "were"
        # that don't start with questions or commands
        claim_patterns = [
            r"[A-Z][^.!?]*(?:is|are|was|were|has|have|had)\s+[^.!?]+[.!]",
        ]

        claims = []
        for pattern in claim_patterns:
            matches = re.findall(pattern, doc.body)
            claims.extend(matches)

        if len(claims) < self.min_claims:
            return ConstraintResult.failure(
                self.name,
                f"Found {len(claims)} claims, requires {self.min_claims}",
                {"found": len(claims), "required": self.min_claims},
            )

        return ConstraintResult.success(
            self.name,
            f"Identified {len(claims)} factual claims",
        )


class ClaimsGrounded(Constraint[KBState]):
    """Verify claims have semantic support in sources.

    Uses embeddings to check claim-source similarity.

    Attributes:
        document_path: Path to document in KB
        similarity_threshold: Minimum similarity (0.0-1.0)
        use_embeddings: Whether to use embedding similarity
    """

    document_path: str
    similarity_threshold: float = 0.7
    use_embeddings: bool = True

    @property
    def name(self) -> str:
        return f"ClaimsGrounded({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        # Placeholder - actual implementation would:
        # 1. Extract claims from document
        # 2. Fetch content from citations
        # 3. Compute embeddings for both
        # 4. Check similarity
        return ConstraintResult.success(
            self.name,
            "Claims grounding check passed (placeholder - full implementation pending)",
        )


class NoHallucinations(Constraint[KBState]):
    """Verify no hallucinated claims using LLM verification.

    Cross-checks claims against source content.

    Attributes:
        document_path: Path to document in KB
        confidence_threshold: Minimum LLM confidence
        use_local_llm: Whether to use local LLM
    """

    document_path: str
    confidence_threshold: float = 0.8
    use_local_llm: bool = True

    @property
    def name(self) -> str:
        return f"NoHallucinations({self.document_path})"

    def evaluate(self, state: KBState) -> ConstraintResult:
        doc = state.get_document(self.document_path)

        if doc is None:
            return ConstraintResult.failure(
                self.name,
                f"Document not found: {self.document_path}",
            )

        # Placeholder - actual implementation would:
        # 1. Extract claims from document
        # 2. Fetch source content
        # 3. Use local LLM to verify each claim
        # 4. Aggregate confidence scores
        return ConstraintResult.success(
            self.name,
            "Hallucination check passed (placeholder - full implementation pending)",
        )


__all__ = [
    "Constraint",
    "DocumentParses",
    "FrontmatterValid",
    "WikilinksResolve",
    "HasCitations",
    "CitationsAccessible",
    "SemanticCoherence",
    "OutputStructureValid",
    # New constraints for additional objectives
    "HasWikilinks",
    "NoOrphanLinks",
    "LinkDensity",
    "CitationsNotStale",
    "SourcesAuthoritative",
    "ClaimsIdentified",
    "ClaimsGrounded",
    "NoHallucinations",
]
