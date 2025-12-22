"""KB (Knowledge Base) Domain for RASE.

Provides KB-specific implementations of the RASE metamodel:
- KBState: System state model implementing SystemState protocol
- KB constraints: Constraint[KBState] implementations for document verification
- KBOracle: Oracle[KBState] for intrinsic verification of objectives

This domain enables De Novo Objective Elucidation - objectives as first-class
KB entities that can be intrinsically verified through the RASE infrastructure.

Key Concepts:
- Objectives are capabilities-in-reverse: they describe what the system is
  trying to achieve and how to verify it
- Verification uses the KB itself as ground truth (API-as-oracle pattern)
- Gates provide progressive verification: syntactic → semantic → empirical

Usage:
    from gaius.rase.domains.kb import (
        KBState, KBDocument,
        DocumentParses, WikilinksResolve, HasCitations,
        KBOracle,
        Objective, ObjectiveFrontmatter, ObjectiveGate,
    )

    # Load objective from KB
    objective = Objective.from_file("current/objectives/rsv.md")

    # Create oracle and verify
    oracle = KBOracle(kb_root="build/dev")
    result = await oracle.verify_objective(objective)

    print(f"Verdict: {result.verdict}, Reward: {result.reward}")
"""

from gaius.rase.domains.base import DomainSpec
from gaius.rase.traceability import IdScheme

# State model
from .state import (
    KBState,
    KBDocument,
    KBLink,
    Citation,
)

# Objective model
from .objective import (
    Objective,
    ObjectiveFrontmatter,
    ObjectiveGate,
    GateLevel,
)

# Constraints
from .constraints import (
    Constraint,
    DocumentParses,
    WikilinksResolve,
    HasCitations,
    CitationsAccessible,
    SemanticCoherence,
    FrontmatterValid,
    OutputStructureValid,
    # Wikilink integrity constraints
    HasWikilinks,
    NoOrphanLinks,
    LinkDensity,
    # Citation freshness constraints
    CitationsNotStale,
    SourcesAuthoritative,
    # Semantic grounding constraints
    ClaimsIdentified,
    ClaimsGrounded,
    NoHallucinations,
    # Provenance/sync constraints
    SourceInSync,
    ProvenanceComplete,
)

# Content provenance tracking
from .provenance import (
    SourceType,
    TransformType,
    Transform,
    ContentSource,
    KBResourceLineage,
    FreshnessCheck,
    check_source_freshness,
    compute_content_hash,
    extract_version_from_url,
    # Database integration
    get_lineage_from_db,
    get_sync_state_from_db,
    record_lineage_event,
)

# Ontology constraints
from .ontology_constraints import (
    OntologyLoads,
    HasComplexClasses,
    ClassesVerbalizable,
    TopicsRecoverable,
    CorpusGenerated,
)

# Corpus storage
from .corpus import (
    CorpusExample,
    CorpusMetadata,
    CorpusWriteResult,
    CorpusStorage,
    get_corpus_storage,
    load_training_examples,
    load_training_examples_async,
)

# Text classification for coherence validation
from .text_classification import (
    ClassificationResult,
    OntologyCoherenceClassifier,
    compute_coherence_score,
)

# Verification
from .verification import (
    KBVerificationCase,
    objective_to_verification_case,
)

# Oracle
from .oracle import KBOracle

# Evidence capture
from .evidence import (
    capture_verification_evidence,
    create_evidence_record,
)

# Domain specification for registry
DOMAIN_SPEC = DomainSpec(
    name="kb",
    state_type=KBState,
    oracle_type=KBOracle,
    constraints={
        "DocumentParses": DocumentParses,
        "WikilinksResolve": WikilinksResolve,
        "HasCitations": HasCitations,
        "CitationsAccessible": CitationsAccessible,
        "SemanticCoherence": SemanticCoherence,
        "FrontmatterValid": FrontmatterValid,
        "OutputStructureValid": OutputStructureValid,
        # Wikilink integrity
        "HasWikilinks": HasWikilinks,
        "NoOrphanLinks": NoOrphanLinks,
        "LinkDensity": LinkDensity,
        # Citation freshness
        "CitationsNotStale": CitationsNotStale,
        "SourcesAuthoritative": SourcesAuthoritative,
        # Semantic grounding
        "ClaimsIdentified": ClaimsIdentified,
        "ClaimsGrounded": ClaimsGrounded,
        "NoHallucinations": NoHallucinations,
        # Provenance/sync constraints
        "SourceInSync": SourceInSync,
        "ProvenanceComplete": ProvenanceComplete,
        # Ontology constraints
        "OntologyLoads": OntologyLoads,
        "HasComplexClasses": HasComplexClasses,
        "ClassesVerbalizable": ClassesVerbalizable,
        "TopicsRecoverable": TopicsRecoverable,
        "CorpusGenerated": CorpusGenerated,
    },
    id_scheme=IdScheme.RASE,  # Uses rase:// scheme for KB objectives
    features_dir="features/kb",
    description="Knowledge Base domain for de novo objective elucidation and intrinsic verification",
)

__all__ = [
    # Domain spec
    "DOMAIN_SPEC",
    # State model
    "KBState",
    "KBDocument",
    "KBLink",
    "Citation",
    # Objective model
    "Objective",
    "ObjectiveFrontmatter",
    "ObjectiveGate",
    "GateLevel",
    # Constraints
    "Constraint",
    "DocumentParses",
    "WikilinksResolve",
    "HasCitations",
    "CitationsAccessible",
    "SemanticCoherence",
    "FrontmatterValid",
    "OutputStructureValid",
    # Wikilink integrity
    "HasWikilinks",
    "NoOrphanLinks",
    "LinkDensity",
    # Citation freshness
    "CitationsNotStale",
    "SourcesAuthoritative",
    # Semantic grounding
    "ClaimsIdentified",
    "ClaimsGrounded",
    "NoHallucinations",
    # Provenance/sync constraints
    "SourceInSync",
    "ProvenanceComplete",
    # Provenance tracking
    "SourceType",
    "TransformType",
    "Transform",
    "ContentSource",
    "KBResourceLineage",
    "FreshnessCheck",
    "check_source_freshness",
    "compute_content_hash",
    "extract_version_from_url",
    # Database integration
    "get_lineage_from_db",
    "get_sync_state_from_db",
    "record_lineage_event",
    # Ontology constraints
    "OntologyLoads",
    "HasComplexClasses",
    "ClassesVerbalizable",
    "TopicsRecoverable",
    "CorpusGenerated",
    # Corpus storage
    "CorpusExample",
    "CorpusMetadata",
    "CorpusWriteResult",
    "CorpusStorage",
    "get_corpus_storage",
    # Text classification
    "ClassificationResult",
    "OntologyCoherenceClassifier",
    "compute_coherence_score",
    # Verification
    "KBVerificationCase",
    "objective_to_verification_case",
    # Oracle
    "KBOracle",
    # Evidence capture
    "capture_verification_evidence",
    "create_evidence_record",
]
