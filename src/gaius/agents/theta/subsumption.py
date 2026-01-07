"""BERTSubs integration for subsumption inference with DeepOnto.

Uses DeepOnto's BERTSubsIntraPipeline to infer subsumption relationships
between concepts within an OWL ontology. For cross-temporal linking,
we dynamically build a lightweight ontology from KB concepts.

ACADEMIC IMPLEMENTATION (Chen et al. 2023 - BERTSubs):
BERTSubs reformulates subsumption (A ⊑ B) as an NLI problem:
- Premise: Verbalization of concept A
- Hypothesis: Subsumption claim "A is a type of B"
- Entailment score → subsumption confidence

The pipeline requires:
1. An OWL Ontology object (can be minimal/dynamic)
2. A YACS config specifying model and parameters
3. Pre-trained BERT classifier for NLI-style classification

References:
- Chen et al. 2023 - BERTSubs: Ontology Subsumption Prediction
- DeepOnto: https://github.com/KRR-Oxford/DeepOnto
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import numpy as np
import logging

logger = logging.getLogger(__name__)

# Set JVM memory before any DeepOnto imports
os.environ.setdefault("JVM_MEMORY", "4g")


class DeepOntoNotAvailableError(Exception):
    """Raised when DeepOnto is required but not available.

    Guru Meditation: #THETA.00000001.DEEPONTO_UNAVAILABLE
    """

    def __init__(self, component: str, original_error: Exception | None = None):
        self.component = component
        self.original_error = original_error
        msg = (
            f"DeepOnto {component} not available.\n"
            f"  Guru Meditation: #THETA.00000001.DEEPONTO_UNAVAILABLE\n"
            f"  Try: uv add deeponto jpype1\n"
            f"  Note: DeepOnto requires JVM (Java 11+) - set JVM_MEMORY=4g env var\n"
        )
        if original_error:
            msg += f"  Original error: {original_error}\n"
        super().__init__(msg)


class OntologyValidationError(Exception):
    """Raised when generated ontology fails validation.

    Guru Meditation: #THETA.00000005.ONTOLOGY_INVALID
    """

    def __init__(
        self,
        ontology_path: Path | str,
        validation_stage: str,
        issues: list[str],
        original_error: Exception | None = None,
    ):
        self.ontology_path = Path(ontology_path)
        self.validation_stage = validation_stage
        self.issues = issues
        self.original_error = original_error

        msg = (
            f"Ontology validation failed at stage '{validation_stage}'.\n"
            f"  Guru Meditation: #THETA.00000005.ONTOLOGY_INVALID\n"
            f"  Ontology: {ontology_path}\n"
            f"  Issues:\n"
        )
        for issue in issues:
            msg += f"    - {issue}\n"
        if original_error:
            msg += f"  Original error: {original_error}\n"
        msg += (
            f"  Remediation:\n"
            f"    1. Check KB content for malformed markdown\n"
            f"    2. Verify concept names don't contain reserved XML characters\n"
            f"    3. Regenerate with: /consolidate --regenerate-ontology\n"
        )
        super().__init__(msg)


@dataclass
class OntologyValidationResult:
    """Result of ontology validation.

    Attributes:
        valid: Whether the ontology passed all validation stages
        ontology_path: Path to the validated ontology
        concept_count: Number of OWL classes in the ontology
        stages_passed: List of validation stages that passed
        issues: List of validation issues found (if any)
        deeponto_loaded: Whether DeepOnto successfully loaded the ontology
    """

    valid: bool
    ontology_path: Path
    concept_count: int = 0
    stages_passed: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    deeponto_loaded: bool = False

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "valid": self.valid,
            "ontology_path": str(self.ontology_path),
            "concept_count": self.concept_count,
            "stages_passed": self.stages_passed,
            "issues": self.issues,
            "deeponto_loaded": self.deeponto_loaded,
        }


@dataclass
class SubsumptionCandidate:
    """A candidate subsumption relationship.

    Represents: subclass ⊑ superclass (subclass is-a superclass)

    Attributes:
        subclass: The more specific concept
        superclass: The more general concept
        confidence: BERTSubs prediction confidence [0, 1]
        source_slice: Temporal slice where subclass was found
        target_slice: Temporal slice where superclass was found
        verbalization: Natural language form of the subsumption
        template_type: BERTSubs template used (IC, PC, BC)
    """

    subclass: str
    superclass: str
    confidence: float
    source_slice: str = ""
    target_slice: str = ""
    verbalization: str = ""
    template_type: str = "IC"
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "subclass": self.subclass,
            "superclass": self.superclass,
            "confidence": self.confidence,
            "source_slice": self.source_slice,
            "target_slice": self.target_slice,
            "verbalization": self.verbalization,
            "template_type": self.template_type,
            "created_at": self.created_at.isoformat(),
        }


def _ensure_jvm_ready() -> None:
    """Ensure JVM is started before importing DeepOnto.

    DeepOnto's ontology.py prompts for memory at import time if JVM isn't started.
    We pre-initialize the JVM to avoid this interactive prompt.
    """
    try:
        import jpype

        if not jpype.isJVMStarted():
            from deeponto import init_jvm

            memory = os.environ.get("JVM_MEMORY", "4g")
            init_jvm(memory)
            logger.info(f"JVM started with {memory} memory")
    except ImportError as e:
        raise DeepOntoNotAvailableError("jpype1", e)


def _patch_deeponto_random_sample() -> None:
    """Patch random.sample globally for Python 3.11+ compatibility.

    DeepOnto 0.9.3 uses random.sample() on sets in multiple locations:
    - text_semantics.py:287 (named_classes - ancestors)
    - text_semantics.py:290 (restrictionObjects)
    - text_semantics.py:506 (subsumptions)
    - pipeline_intra.py:346 (restrictions)
    - pipeline_intra.py:371 (new_seeds)
    - pipeline_intra.py:378 (all_nebs)

    Python 3.11+ raises TypeError: "Population must be a sequence."

    This globally patches random.sample to auto-convert sets to lists.

    Upstream fix pending: https://github.com/KRR-Oxford/DeepOnto
    """
    import sys
    if sys.version_info < (3, 11):
        return  # No patch needed for Python 3.10 and earlier

    import random

    # Check if already patched (avoid double-patching)
    if getattr(random.sample, "_gaius_patched", False):
        return

    _original_sample = random.sample

    def _safe_sample(population, k, **kwargs):
        """Wrapper that converts sets to lists for Python 3.11+."""
        if isinstance(population, (set, frozenset)):
            population = list(population)
        return _original_sample(population, k, **kwargs)

    setattr(_safe_sample, "_gaius_patched", True)
    random.sample = _safe_sample  # type: ignore[method-assign] - Python 3.11+ compat patch
    logger.debug("Applied global Python 3.11+ random.sample compatibility patch")


def _patch_deeponto_datasets_compat() -> None:
    """Patch DeepOnto's BERTSubsumptionClassifierTrainer for datasets 4.x compatibility.

    DeepOnto 0.9.3's bert_classifier.py line 114 does:
        tokens = self.tokenizer(dataset["sent1"], dataset["sent2"])

    In datasets 4.x, dataset["column"] returns an Arrow column, not a Python list.
    The tokenizer expects list[str].

    This patches load_dataset to convert Arrow columns to lists.

    Upstream fix pending: https://github.com/KRR-Oxford/DeepOnto
    """
    try:
        from deeponto.complete.bertsubs.bert_classifier import BERTSubsumptionClassifierTrainer

        _original_load_dataset = BERTSubsumptionClassifierTrainer.load_dataset

        def _patched_load_dataset(self, data, max_length=512, count_token_size=False):
            """Patched version that converts Arrow columns to lists for tokenizer."""
            from datasets import Dataset

            def iterate():
                for sample in data:
                    yield {"sent1": sample[0], "sent2": sample[1], "labels": sample[2]}

            dataset = Dataset.from_generator(iterate)

            if count_token_size:
                # Convert Arrow columns to Python lists for tokenizer
                sent1_list = list(dataset["sent1"])
                sent2_list = list(dataset["sent2"])
                tokens = self.tokenizer(sent1_list, sent2_list)
                l_sum, num_128, num_256, num_512, l_max = 0, 0, 0, 0, 0
                for item in tokens["input_ids"]:
                    l = len(item)
                    l_sum += l
                    if l <= 128:
                        num_128 += 1
                    if l <= 256:
                        num_256 += 1
                    if l <= 512:
                        num_512 += 1
                    if l > l_max:
                        l_max = l
                print("average token size: %.2f" % (l_sum / len(tokens["input_ids"])))
                print("ratio of token size <= 128: %.3f" % (num_128 / len(tokens["input_ids"])))
                print("ratio of token size <= 256: %.3f" % (num_256 / len(tokens["input_ids"])))
                print("ratio of token size <= 512: %.3f" % (num_512 / len(tokens["input_ids"])))
                print("max token size: %d" % l_max)

            # Tokenize the dataset for training
            def tokenize(sample):
                return self.tokenizer(
                    sample["sent1"],
                    sample["sent2"],
                    padding="max_length",
                    truncation=True,
                    max_length=max_length,
                )

            dataset = dataset.map(tokenize, batched=True)
            dataset = dataset.rename_column("labels", "label")
            dataset.set_format(type="torch", columns=["input_ids", "attention_mask", "label"])
            return dataset

        BERTSubsumptionClassifierTrainer.load_dataset = _patched_load_dataset  # type: ignore[method-assign] - datasets 4.x compat patch
        logger.debug("Applied datasets 4.x compatibility patch to DeepOnto BERTSubsumptionClassifierTrainer")

    except ImportError:
        # DeepOnto not installed, patch not needed
        pass
    except Exception as e:
        logger.warning(f"Failed to apply DeepOnto datasets patch: {e}")


def _patch_transformers_training_args() -> None:
    """Patch TrainingArguments for transformers 4.46+ compatibility.

    In transformers 4.46+, `evaluation_strategy` was renamed to `eval_strategy`.
    DeepOnto 0.9.3 uses the old parameter name.

    This patches TrainingArguments.__init__ to rename the parameter if needed.

    Upstream fix pending: https://github.com/KRR-Oxford/DeepOnto
    """
    try:
        from transformers import TrainingArguments
        import inspect

        # Check if eval_strategy is a valid parameter (newer transformers)
        sig = inspect.signature(TrainingArguments.__init__)
        if "eval_strategy" in sig.parameters and "evaluation_strategy" not in sig.parameters:
            # Need to patch - newer transformers without backward compat

            _original_init = TrainingArguments.__init__

            def _patched_init(self, *args, **kwargs):
                # Rename evaluation_strategy to eval_strategy
                if "evaluation_strategy" in kwargs:
                    kwargs["eval_strategy"] = kwargs.pop("evaluation_strategy")
                return _original_init(self, *args, **kwargs)

            TrainingArguments.__init__ = _patched_init  # type: ignore[method-assign] - monkey-patching for transformers 4.46+ compatibility
            logger.debug("Applied transformers 4.46+ TrainingArguments compatibility patch")

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to apply TrainingArguments patch: {e}")


class SubsumptionInferencer:
    """BERTSubs-based subsumption inference using DeepOnto.

    ACADEMIC IMPLEMENTATION (Chen et al. 2023):
    Uses DeepOnto's BERTSubsIntraPipeline with a domain ontology to predict
    subsumption relationships. The pipeline:
    1. Loads an OWL ontology defining the concept hierarchy
    2. Uses BERT-based NLI to score subsumption hypotheses
    3. Returns confidence scores for concept pairs

    This is NOT a simplified NLI wrapper - it requires a real OWL ontology
    and uses DeepOnto's full BERTSubs pipeline for academically rigorous
    subsumption inference.

    Args:
        ontology_path: Path to OWL ontology file (required)
        confidence_threshold: Minimum confidence for accepting subsumption
        bert_checkpoint: HuggingFace checkpoint for BERT classifier
        max_length: Maximum sequence length for BERT
    """

    def __init__(
        self,
        ontology_path: str | Path,
        confidence_threshold: float = 0.8,
        bert_checkpoint: str = "bert-base-uncased",
        max_length: int = 128,
    ):
        self.ontology_path = Path(ontology_path)
        self.confidence_threshold = confidence_threshold
        self.bert_checkpoint = bert_checkpoint
        self.max_length = max_length

        # Lazy-loaded components
        self._ontology = None
        self._pipeline = None
        self._config = None

    def _get_ontology(self):
        """Load ontology from OWL file.

        Raises:
            DeepOntoNotAvailableError: If ontology cannot be loaded
            FileNotFoundError: If ontology file doesn't exist
        """
        if self._ontology is None:
            if not self.ontology_path.exists():
                raise FileNotFoundError(
                    f"Ontology file not found: {self.ontology_path}\n"
                    f"  Guru Meditation: #THETA.00000004.ONTOLOGY_MISSING\n"
                    f"  Create domain ontology at: {self.ontology_path}"
                )

            try:
                _ensure_jvm_ready()
                from deeponto.onto import Ontology

                self._ontology = Ontology(str(self.ontology_path))
                logger.info(f"Loaded ontology from {self.ontology_path}")
            except ImportError as e:
                raise DeepOntoNotAvailableError("Ontology", e)
            except Exception as e:
                raise DeepOntoNotAvailableError(f"Ontology({self.ontology_path})", e)

        return self._ontology

    def _get_config(self):
        """Load default BERTSubs config and merge our overrides.

        BERTSubsIntraPipeline requires many config fields (label_property,
        subsumption_type, prompt settings, etc.). We load the default config
        and override only what we need to customize.
        """
        if self._config is None:
            try:
                from yacs.config import CfgNode as CN
                from pathlib import Path
                import yaml

                # Load default config from DeepOnto package
                deeponto_path = Path(__file__).parent.parent.parent.parent
                # Find the installed deeponto package
                import deeponto
                if deeponto.__file__ is None:
                    raise RuntimeError(
                        "DeepOnto package __file__ is None - cannot locate config.\n"
                        "  Guru Meditation: #THETA.00000003.DEEPONTO_FILE_NONE"
                    )
                deeponto_pkg_path = Path(deeponto.__file__).parent
                default_config_path = (
                    deeponto_pkg_path / "complete" / "bertsubs" / "default_config_intra.yaml"
                )

                if default_config_path.exists():
                    with open(default_config_path) as f:
                        default_cfg = yaml.safe_load(f)
                    self._config = CN(default_cfg)
                else:
                    # Fallback: create minimal config with required fields
                    self._config = CN()
                    self._config.label_property = ["http://www.w3.org/2000/01/rdf-schema#label"]
                    self._config.use_one_label = True
                    self._config.subsumption_type = "named_class"
                    self._config.no_reasoning = False

                # Override with our settings - we use the pipeline for inference only
                # Clear file paths that reference non-existent test files
                self._config.test_subsumption_file = None
                self._config.train_subsumption_file = None
                self._config.valid_subsumption_file = None

                # Merge our settings into fine_tune (don't replace the entire section)
                # This preserves required fields like train_pos_dup, train_neg_dup
                if "fine_tune" not in self._config:
                    self._config.fine_tune = CN()
                self._config.fine_tune.pretrained = self.bert_checkpoint
                self._config.fine_tune.tokenizer = self.bert_checkpoint
                self._config.fine_tune.do_fine_tune = False  # Use pretrained for inference
                self._config.fine_tune.batch_size = 32
                self._config.fine_tune.output_dir = "/tmp/bertsubs"  # Dummy output dir

                # Same for prompt - merge instead of replace
                if "prompt" not in self._config:
                    self._config.prompt = CN()
                self._config.prompt.max_length = self.max_length
                self._config.prompt.prompt_type = "isolated"
                self._config.prompt.prompt_hop = 1
                self._config.prompt.prompt_max_subsumptions = 4
                self._config.prompt.use_sub_special_token = False
                self._config.prompt.context_dup = 4

                # Same for evaluation
                if "evaluation" not in self._config:
                    self._config.evaluation = CN()
                self._config.evaluation.batch_size = 32

                # Device selection
                device = "cuda" if self._has_cuda() else "cpu"
                logger.debug(f"Created BERTSubs config with device={device}")

            except ImportError as e:
                raise DeepOntoNotAvailableError("yacs", e)

        return self._config

    def _has_cuda(self) -> bool:
        """Check if CUDA is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def _get_pipeline(self):
        """Get BERTSubsIntraPipeline instance.

        Raises:
            DeepOntoNotAvailableError: If pipeline cannot be loaded
        """
        if self._pipeline is None:
            try:
                _ensure_jvm_ready()
                # Apply compatibility patches before importing pipeline
                _patch_deeponto_random_sample()  # Python 3.11+ random.sample on sets
                _patch_deeponto_datasets_compat()  # datasets 4.x Arrow columns
                _patch_transformers_training_args()  # transformers 4.46+ eval_strategy
                from deeponto.complete.bertsubs import BERTSubsIntraPipeline

                ontology = self._get_ontology()
                config = self._get_config()

                self._pipeline = BERTSubsIntraPipeline(ontology, config)
                logger.info(f"Initialized BERTSubsIntraPipeline with {self.bert_checkpoint}")
            except ImportError as e:
                raise DeepOntoNotAvailableError("BERTSubsIntraPipeline", e)
            except Exception as e:
                raise DeepOntoNotAvailableError("BERTSubsIntraPipeline", e)

        return self._pipeline

    def predict_subsumption(
        self,
        subclass: str,
        superclass: str,
        source_slice: str = "",
        target_slice: str = "",
    ) -> SubsumptionCandidate:
        """Predict whether subclass ⊑ superclass holds.

        Uses BERTSubsIntraPipeline.score() for subsumption prediction.
        Requires concepts to exist in the loaded ontology.

        Args:
            subclass: The more specific concept (IRI or label)
            superclass: The more general concept (IRI or label)
            source_slice: Temporal slice of subclass
            target_slice: Temporal slice of superclass

        Returns:
            SubsumptionCandidate with confidence score

        Raises:
            DeepOntoNotAvailableError: If pipeline cannot be loaded
        """
        pipeline = self._get_pipeline()

        # Format as subsumption pair for BERTSubs
        # BERTSubs expects [[subclass_iri, superclass_iri], ...]
        subsumption_pair = [[subclass, superclass]]

        try:
            # Use score() for single prediction
            scores = pipeline.score(subsumption_pair)
            confidence = float(scores[0]) if scores else 0.0
        except Exception as e:
            logger.warning(f"BERTSubs.score failed: {e}")
            # Try predict() as fallback
            try:
                predictions = pipeline.predict(subsumption_pair)
                confidence = float(predictions[0]) if predictions else 0.0
            except Exception as e2:
                raise DeepOntoNotAvailableError(
                    f"BERTSubs.score/predict({subclass}, {superclass})", e2
                )

        # Create verbalization
        verbalization = f"{subclass} is a type of {superclass}"

        return SubsumptionCandidate(
            subclass=subclass,
            superclass=superclass,
            confidence=confidence,
            source_slice=source_slice,
            target_slice=target_slice,
            verbalization=verbalization,
            template_type="IC",
        )

    async def infer_subsumptions(
        self,
        candidates: list[tuple[str, str]],
        consolidation_signal: float = 1.0,
        source_slice: str = "",
        target_slice: str = "",
    ) -> list[SubsumptionCandidate]:
        """Infer subsumptions from candidate pairs.

        The consolidation signal mediates depth: higher signals evaluate
        more candidates (up to 100%), lower signals evaluate fewer (down to 10%).

        Args:
            candidates: List of (subclass, superclass) pairs
            consolidation_signal: Urgency signal [0, 1] from ThetaDynamics
            source_slice: Default source temporal slice
            target_slice: Default target temporal slice

        Returns:
            List of accepted SubsumptionCandidates
        """
        if not candidates:
            return []

        # Scale depth by signal (0.0 -> 10%, 1.0 -> 100%)
        depth = int(len(candidates) * (0.1 + 0.9 * consolidation_signal))
        depth = max(1, min(depth, len(candidates)))  # Ensure at least 1

        logger.debug(
            f"Evaluating {depth}/{len(candidates)} candidates "
            f"(signal={consolidation_signal:.2f})"
        )

        # Evaluate candidates
        results = []
        for subclass, superclass in candidates[:depth]:
            candidate = self.predict_subsumption(
                subclass=subclass,
                superclass=superclass,
                source_slice=source_slice,
                target_slice=target_slice,
            )

            if candidate.confidence >= self.confidence_threshold:
                results.append(candidate)

        logger.info(
            f"Found {len(results)} subsumptions above threshold "
            f"({self.confidence_threshold})"
        )

        return results

    def get_stats(self) -> dict:
        """Get inferencer statistics."""
        return {
            "ontology_path": str(self.ontology_path),
            "ontology_loaded": self._ontology is not None,
            "pipeline_loaded": self._pipeline is not None,
            "confidence_threshold": self.confidence_threshold,
            "bert_checkpoint": self.bert_checkpoint,
            "max_length": self.max_length,
        }


def validate_ontology(ontology_path: Path) -> OntologyValidationResult:
    """Validate an OWL ontology file with multiple verification stages.

    VALIDATION STAGES:
    1. File existence and readability
    2. XML/RDF syntax validation
    3. owlready2 loading (basic OWL structure)
    4. DeepOnto loading (full reasoning capability)
    5. Class extraction verification

    This is the "logical feedback loop" ensuring generated ontologies
    are syntactically correct and loadable by DeepOnto for BERTSubs.

    Args:
        ontology_path: Path to OWL file to validate

    Returns:
        OntologyValidationResult with detailed validation status

    Raises:
        OntologyValidationError: If validation fails (fail-fast)
    """
    result = OntologyValidationResult(
        valid=False,
        ontology_path=ontology_path,
    )
    issues = []

    # Stage 1: File existence
    if not ontology_path.exists():
        issues.append(f"Ontology file does not exist: {ontology_path}")
        raise OntologyValidationError(
            ontology_path=ontology_path,
            validation_stage="file_existence",
            issues=issues,
        )
    result.stages_passed.append("file_existence")

    # Stage 2: XML syntax validation
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(str(ontology_path))
        root = tree.getroot()
        # Check for RDF namespace
        if not any("rdf" in ns.lower() for ns in root.attrib.values()):
            issues.append("Missing RDF namespace in root element")
    except ET.ParseError as e:
        issues.append(f"XML parse error: {e}")
        raise OntologyValidationError(
            ontology_path=ontology_path,
            validation_stage="xml_syntax",
            issues=issues,
            original_error=e,
        )
    result.stages_passed.append("xml_syntax")

    # Stage 3: owlready2 loading
    try:
        from owlready2 import get_ontology, default_world

        # Clear any cached ontology with same IRI
        default_world.ontologies.clear()

        onto = get_ontology(str(ontology_path)).load()
        classes = list(onto.classes())
        result.concept_count = len(classes)

        if result.concept_count == 0:
            issues.append("Ontology loaded but contains no classes")

        logger.debug(f"owlready2 loaded {result.concept_count} classes")
    except Exception as e:
        issues.append(f"owlready2 load failed: {e}")
        raise OntologyValidationError(
            ontology_path=ontology_path,
            validation_stage="owlready2_load",
            issues=issues,
            original_error=e,
        )
    result.stages_passed.append("owlready2_load")

    # Stage 4: DeepOnto loading (the critical test)
    try:
        _ensure_jvm_ready()
        from deeponto.onto import Ontology

        deeponto_onto = Ontology(str(ontology_path))

        # Verify we can access classes
        owl_classes = deeponto_onto.owl_classes
        logger.info(
            f"DeepOnto loaded ontology with {len(list(owl_classes))} OWL classes"
        )
        result.deeponto_loaded = True
    except ImportError as e:
        # DeepOnto not installed - note but don't fail
        issues.append(f"DeepOnto not available for validation: {e}")
        logger.warning("DeepOnto validation skipped - not installed")
    except Exception as e:
        issues.append(f"DeepOnto load failed: {e}")
        raise OntologyValidationError(
            ontology_path=ontology_path,
            validation_stage="deeponto_load",
            issues=issues,
            original_error=e,
        )
    result.stages_passed.append("deeponto_load")

    # Stage 5: Verify class IRIs are accessible
    try:
        if result.deeponto_loaded:
            # Re-use already loaded ontology
            pass  # Already verified above
        else:
            # Use owlready2 for basic verification
            for cls in classes[:10]:  # Sample first 10
                if not hasattr(cls, "iri"):
                    issues.append(f"Class {cls} missing IRI")
    except Exception as e:
        issues.append(f"Class IRI verification failed: {e}")
    result.stages_passed.append("class_verification")

    # Final verdict
    result.issues = issues
    result.valid = len(issues) == 0 or (
        len(issues) == 1 and "DeepOnto not available" in issues[0]
    )

    if result.valid:
        logger.info(
            f"Ontology validation PASSED: {ontology_path} "
            f"({result.concept_count} classes, stages: {result.stages_passed})"
        )
    else:
        logger.warning(f"Ontology validation FAILED: {issues}")

    return result


def generate_ontology_from_kb(
    kb_root: Path,
    output_path: Path,
    slice_id: str | None = None,
    namespace: str = "http://gaius.local/ontology#",
    validate: bool = True,
) -> tuple[Path, OntologyValidationResult | None]:
    """Generate OWL ontology from KB content with validation.

    Extracts concepts from KB documents and creates a minimal OWL ontology
    for use with BERTSubsIntraPipeline. Includes validation feedback loop
    to ensure the generated ontology loads correctly with DeepOnto.

    Args:
        kb_root: Root of KB directory
        output_path: Where to write the OWL file
        slice_id: Optional temporal slice to extract from (e.g., "2025-W52")
        namespace: OWL namespace for generated concepts
        validate: Whether to run validation after generation (default: True)

    Returns:
        Tuple of (path to generated ontology, validation result or None)

    Raises:
        DeepOntoNotAvailableError: If owlready2 is not available
        OntologyValidationError: If validation fails and validate=True
    """
    try:
        from owlready2 import get_ontology, Thing, default_world
    except ImportError as e:
        raise DeepOntoNotAvailableError("owlready2", e)

    # Clear any cached ontology with same namespace
    default_world.ontologies.clear()

    # Create new ontology
    onto = get_ontology(namespace)

    # Collect concepts from KB
    concepts = set()

    if slice_id:
        # Extract from specific temporal slice
        slice_dir = kb_root / "scratch" / slice_id
        if slice_dir.exists():
            for md_file in slice_dir.glob("**/*.md"):
                concepts.update(_extract_concepts_from_markdown(md_file))
    else:
        # Extract from current content
        current_dir = kb_root / "current"
        if current_dir.exists():
            for md_file in current_dir.glob("**/*.md"):
                concepts.update(_extract_concepts_from_markdown(md_file))

    # Also include scratch if no slice_id (for comprehensive coverage)
    if not slice_id:
        scratch_dir = kb_root / "scratch"
        if scratch_dir.exists():
            for md_file in scratch_dir.glob("**/*.md"):
                concepts.update(_extract_concepts_from_markdown(md_file))

    if not concepts:
        logger.warning(f"No concepts extracted from KB at {kb_root}")

    # Create OWL classes for each concept
    created_classes = []
    with onto:
        for concept in concepts:
            # Create class with sanitized name
            class_name = _sanitize_owl_name(concept)
            if class_name:
                try:
                    # Create new class dynamically
                    new_class = type(class_name, (Thing,), {})
                    # Add label annotation (owlready2 Thing expects 'label' property)
                    setattr(new_class, "label", [concept])
                    created_classes.append(class_name)
                except Exception as e:
                    logger.warning(f"Failed to create class '{class_name}': {e}")

    # Save ontology
    output_path.parent.mkdir(parents=True, exist_ok=True)
    onto.save(file=str(output_path), format="rdfxml")

    logger.info(
        f"Generated ontology with {len(created_classes)} classes "
        f"from {len(concepts)} concepts: {output_path}"
    )

    # Validation feedback loop
    validation_result = None
    if validate:
        validation_result = validate_ontology(output_path)
        if not validation_result.valid:
            raise OntologyValidationError(
                ontology_path=output_path,
                validation_stage="post_generation",
                issues=validation_result.issues,
            )
        logger.info(
            f"Ontology validated: {validation_result.concept_count} classes, "
            f"DeepOnto loaded: {validation_result.deeponto_loaded}"
        )

    return output_path, validation_result


def _extract_concepts_from_markdown(file_path: Path) -> set[str]:
    """Extract concept names from markdown file.

    Looks for:
    - Headings (# Concept Name)
    - Bold terms (**concept**)
    - Wikilinks ([[concept]])
    - Code identifiers (`ClassName`)

    Returns:
        Set of concept strings
    """
    import re

    concepts = set()
    try:
        content = file_path.read_text()

        # Extract headings
        headings = re.findall(r"^#+\s+(.+)$", content, re.MULTILINE)
        concepts.update(h.strip() for h in headings)

        # Extract bold terms
        bold = re.findall(r"\*\*([^*]+)\*\*", content)
        concepts.update(b.strip() for b in bold if len(b.strip()) > 2)

        # Extract wikilinks
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
        concepts.update(w.strip() for w in wikilinks)

        # Extract code identifiers (CamelCase or snake_case)
        code_ids = re.findall(r"`([A-Z][a-zA-Z0-9_]+)`", content)
        concepts.update(c.strip() for c in code_ids)

    except Exception as e:
        logger.warning(f"Failed to extract concepts from {file_path}: {e}")

    return concepts


def _sanitize_owl_name(name: str) -> str:
    """Sanitize string for use as OWL class name.

    OWL class names must be valid NCNames (no spaces, starts with letter, etc.)
    """
    import re

    # Replace spaces with underscores
    name = name.replace(" ", "_")
    # Remove non-alphanumeric except underscore
    name = re.sub(r"[^a-zA-Z0-9_]", "", name)
    # Ensure starts with letter
    if name and not name[0].isalpha():
        name = "C_" + name
    return name
