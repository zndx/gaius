"""ThetaAgent - Neuromorphic Situational Awareness for Gaius.

This module implements a biologically-inspired attention management system
grounded in Graziano's Attention Schema Theory (AST) and hippocampal theta
wave dynamics.

The ThetaAgent provides `/sitrep` as the single pane of glass for daily
situational awareness, synthesizing:
- Objectives and agent thoughts
- Personal agenda (filtered from all project agendas)
- Current events via search/research actions
- Evolving Gaius capabilities

Phase 2 adds NVAR-mediated consolidation:
- ThetaDynamics for consolidation signal computation
- SubsumptionInferencer for BERTSubs-based cross-temporal linking
- KnowledgeGradientPolicy for economic justification

References:
- Graziano, M.S.A. (2013). Consciousness and the Social Brain
- Zhang et al. (2015). Traveling Theta Waves in the Human Hippocampus
- Monaco et al. (2020). Cognitive Swarming with Attractor Dynamics
- Gauthier et al. (2021). Next Generation Reservoir Computing
- Powell & Ryzhov (2012). Optimal Learning
"""

from .horizons import Horizon, HorizonView
from .schema import AttentionTarget, AttentionSchema
from .sitrep import SituationReport, SitrepSection
from .agent import ThetaAgent, ConsolidationResult

# Phase 2: Consolidation
from .consolidation import ThetaDynamics, ConsolidationSignal, TemporalSlice
from .subsumption import (
    SubsumptionInferencer,
    SubsumptionCandidate,
    DeepOntoNotAvailableError,
    OntologyValidationError,
    OntologyValidationResult,
    generate_ontology_from_kb,
    validate_ontology,
)
from .augmentation import (
    inject_wikilinks,
    inject_action_links,
    inject_mixed,
    strip_augmentation,
    has_augmentation,
    AugmentationResult,
)
from .effectiveness import (
    EffectivenessResult,
    EffectivenessTracker,
    compute_augmentation_contribution,
    SHAPAnalyzer,
    SHAPAttribution,
    SHAPNotAvailableError,
    SHAP_AVAILABLE,
)
from .kg_policy import (
    KnowledgeGradientPolicy,
    BeliefState,
    ConsolidationDecision,
)

__all__ = [
    # Phase 1: SITREP
    "ThetaAgent",
    "ConsolidationResult",
    "Horizon",
    "HorizonView",
    "AttentionTarget",
    "AttentionSchema",
    "SituationReport",
    "SitrepSection",
    # Phase 2: Consolidation
    "ThetaDynamics",
    "ConsolidationSignal",
    "TemporalSlice",
    "SubsumptionInferencer",
    "SubsumptionCandidate",
    "DeepOntoNotAvailableError",
    "OntologyValidationError",
    "OntologyValidationResult",
    "generate_ontology_from_kb",
    "validate_ontology",
    "inject_wikilinks",
    "inject_action_links",
    "inject_mixed",
    "strip_augmentation",
    "has_augmentation",
    "AugmentationResult",
    "EffectivenessResult",
    "EffectivenessTracker",
    "compute_augmentation_contribution",
    "SHAPAnalyzer",
    "SHAPAttribution",
    "SHAPNotAvailableError",
    "SHAP_AVAILABLE",
    # Knowledge Gradient
    "KnowledgeGradientPolicy",
    "BeliefState",
    "ConsolidationDecision",
]
