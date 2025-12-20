"""VM - Verifier Model for RASE.

The Verifier Model defines requirements and verification cases, providing
the oracle for RLVR-style training. This is the core of RASE verification.

Package structure mirrors SysML v2:
    package RASE_NiFi::VM {
        requirement def BDDStepRequirement { ... }
        verification def Verify_CreateBasicFlow { ... }
    }

Key concepts:
- Requirement: A constraint with assume/require semantics
- StepRequirement: Atomic requirement from a BDD step
- ScenarioRequirement: Composite requirement grouping steps
- VerificationCase: Test that verifies requirements
- VerdictKind: PASS/FAIL/INCONCLUSIVE/ERROR
- VerificationResult: Outcome with evidence

The VM enables two key capabilities:
1. Automated verification: Compare agent actions against requirements
2. Reward computation: Generate training signals from verification results

This is "the verifier as a first-class artifact" - specified, reviewed,
tested, and versioned as safety-critical infrastructure.
"""

from .requirements import (
    Requirement,
    StepRequirement,
    ScenarioRequirement,
    FeatureRequirement,
    derive_requirements_from_scenario,
)
from .verification import (
    VerdictKind,
    VerificationObjective,
    VerificationCase,
    APIVerificationCase,
    UIVerificationCase,
    VerificationResult,
    VerificationRun,
)
from .oracle import (
    Oracle,
    NiFiOracle,
    RewardStrategy,
    BinaryReward,
    GradedReward,
    compute_reward,
)

__all__ = [
    # Requirements
    "Requirement",
    "StepRequirement",
    "ScenarioRequirement",
    "FeatureRequirement",
    "derive_requirements_from_scenario",
    # Verification
    "VerdictKind",
    "VerificationObjective",
    "VerificationCase",
    "APIVerificationCase",
    "UIVerificationCase",
    "VerificationResult",
    "VerificationRun",
    # Oracle
    "Oracle",
    "NiFiOracle",
    "RewardStrategy",
    "BinaryReward",
    "GradedReward",
    "compute_reward",
]
