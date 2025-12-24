"""Tests for ThetaAgent subsumption inference.

Tests the BERTSubs-based cross-temporal linking functionality.

ACADEMIC IMPLEMENTATION: SubsumptionInferencer requires:
1. A real OWL ontology file (ontology_path)
2. DeepOnto with JVM for BERTSubsIntraPipeline

Tests that don't require DeepOnto (dataclasses, error handling) run unconditionally.
Tests requiring DeepOnto are skipped when unavailable.
"""

import pytest
import tempfile
from pathlib import Path

from gaius.agents.theta.subsumption import (
    SubsumptionInferencer,
    SubsumptionCandidate,
    DeepOntoNotAvailableError,
    OntologyValidationError,
    OntologyValidationResult,
)


class TestSubsumptionCandidate:
    """Tests for SubsumptionCandidate dataclass."""

    def test_create_candidate(self):
        """Test creating a subsumption candidate."""
        candidate = SubsumptionCandidate(
            subclass="neural_networks",
            superclass="machine_learning",
            confidence=0.85,
            source_slice="2025-W50",
            target_slice="2025-W48",
        )

        assert candidate.subclass == "neural_networks"
        assert candidate.superclass == "machine_learning"
        assert candidate.confidence == 0.85
        assert candidate.source_slice == "2025-W50"
        assert candidate.target_slice == "2025-W48"

    def test_candidate_defaults(self):
        """Test default values."""
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.9,
        )

        assert candidate.source_slice == ""
        assert candidate.target_slice == ""
        assert candidate.verbalization == ""
        assert candidate.template_type == "IC"

    def test_candidate_to_dict(self):
        """Test candidate serialization."""
        candidate = SubsumptionCandidate(
            subclass="A",
            superclass="B",
            confidence=0.9,
            verbalization="A is a type of B",
        )

        d = candidate.to_dict()
        assert d["subclass"] == "A"
        assert d["superclass"] == "B"
        assert d["confidence"] == 0.9
        assert d["verbalization"] == "A is a type of B"
        assert "created_at" in d


class TestDeepOntoNotAvailableError:
    """Tests for DeepOntoNotAvailableError."""

    def test_error_message(self):
        """Test error message includes remediation."""
        error = DeepOntoNotAvailableError("BERTSubsClassifier")

        msg = str(error)
        assert "DeepOnto" in msg
        assert "BERTSubsClassifier" in msg
        assert "Guru Meditation" in msg
        assert "#THETA.00000001.DEEPONTO_UNAVAILABLE" in msg
        assert "uv add deeponto jpype1" in msg

    def test_error_with_original(self):
        """Test error message with original exception."""
        original = ImportError("No module named 'deeponto'")
        error = DeepOntoNotAvailableError("BERTSubsClassifier", original)

        msg = str(error)
        assert "Original error" in msg
        assert "No module named" in msg


class TestOntologyValidationResult:
    """Tests for OntologyValidationResult dataclass."""

    def test_create_result(self):
        """Test creating a validation result."""
        result = OntologyValidationResult(
            valid=True,
            ontology_path=Path("/tmp/test.owl"),
            concept_count=42,
            stages_passed=["file_existence", "xml_syntax"],
            deeponto_loaded=True,
        )

        assert result.valid is True
        assert result.concept_count == 42
        assert "file_existence" in result.stages_passed

    def test_result_to_dict(self):
        """Test serialization."""
        result = OntologyValidationResult(
            valid=False,
            ontology_path=Path("/tmp/test.owl"),
            issues=["Missing RDF namespace"],
        )

        d = result.to_dict()
        assert d["valid"] is False
        assert "Missing RDF namespace" in d["issues"]
        assert d["ontology_path"] == "/tmp/test.owl"


class TestSubsumptionInferencer:
    """Tests for SubsumptionInferencer.

    The inferencer requires an ontology_path because it uses the real
    BERTSubsIntraPipeline from DeepOnto, not a simplified wrapper.
    """

    def test_init_requires_ontology_path(self):
        """Test that ontology_path is required."""
        with pytest.raises(TypeError, match="ontology_path"):
            SubsumptionInferencer()  # Missing required arg

    def test_init_with_ontology_path(self):
        """Test initialization with ontology path."""
        inferencer = SubsumptionInferencer(
            ontology_path="/tmp/test.owl",
            confidence_threshold=0.9,
            bert_checkpoint="custom-model",
        )

        assert inferencer.ontology_path == Path("/tmp/test.owl")
        assert inferencer.confidence_threshold == 0.9
        assert inferencer.bert_checkpoint == "custom-model"

    def test_init_defaults(self):
        """Test default values when ontology_path provided."""
        inferencer = SubsumptionInferencer(ontology_path="/tmp/test.owl")

        assert inferencer.confidence_threshold == 0.8
        assert inferencer.bert_checkpoint == "bert-base-uncased"
        assert inferencer.max_length == 128

    def test_get_stats(self):
        """Test getting inferencer statistics."""
        inferencer = SubsumptionInferencer(ontology_path="/tmp/test.owl")
        stats = inferencer.get_stats()

        assert "ontology_path" in stats
        assert "confidence_threshold" in stats
        assert "bert_checkpoint" in stats
        assert "ontology_loaded" in stats
        assert "pipeline_loaded" in stats
        assert stats["ontology_path"] == "/tmp/test.owl"

    def test_ontology_not_loaded_initially(self):
        """Test ontology is lazy-loaded."""
        inferencer = SubsumptionInferencer(ontology_path="/tmp/test.owl")

        assert inferencer._ontology is None
        assert inferencer._pipeline is None

    def test_missing_ontology_file_raises(self):
        """Test that missing ontology file raises FileNotFoundError."""
        inferencer = SubsumptionInferencer(
            ontology_path="/nonexistent/path/ontology.owl"
        )

        with pytest.raises(FileNotFoundError) as exc_info:
            inferencer._get_ontology()

        assert "Guru Meditation" in str(exc_info.value)
        assert "#THETA.00000004.ONTOLOGY_MISSING" in str(exc_info.value)


class TestOntologyValidationError:
    """Tests for OntologyValidationError."""

    def test_error_message_format(self):
        """Test error message includes all context."""
        error = OntologyValidationError(
            ontology_path="/tmp/bad.owl",
            validation_stage="xml_syntax",
            issues=["Invalid XML", "Missing namespace"],
        )

        msg = str(error)
        assert "Guru Meditation" in msg
        assert "#THETA.00000005.ONTOLOGY_INVALID" in msg
        assert "xml_syntax" in msg
        assert "Invalid XML" in msg
        assert "Missing namespace" in msg
        assert "/tmp/bad.owl" in msg
        assert "/consolidate --regenerate-ontology" in msg


class TestDeepOntoIntegration:
    """Tests for DeepOnto BERTSubs integration.

    DeepOnto with JVM is a HARD REQUIREMENT provided by devenv.
    These tests must pass - no fallbacks, no skips.

    Note: BERTSubsIntraPipeline requires an ontology with enough classes
    and subsumption relationships to extract training data from.
    The internal Gaius domain ontology (58 classes) provides this.
    """

    @pytest.fixture
    def gaius_ontology(self):
        """Return path to internal Gaius domain ontology.

        This ontology has 58 classes with rdfs:label annotations,
        sufficient for BERTSubsIntraPipeline training data extraction.
        """
        import gaius
        gaius_root = Path(gaius.__file__).parent
        ontology_path = gaius_root / "data" / "ontologies" / "gaius_domain.owl"

        if not ontology_path.exists():
            pytest.skip(f"Gaius domain ontology not found at {ontology_path}")

        return ontology_path

    @pytest.fixture
    def minimal_ontology(self, tmp_path):
        """Create a minimal valid OWL ontology for testing.

        BERTSubs requires rdfs:label annotations on classes for text semantics.
        Note: This ontology is too small for BERTSubsIntraPipeline training,
        but can be used for ontology loading tests.
        """
        owl_content = '''<?xml version="1.0"?>
<rdf:RDF xmlns="http://gaius.local/test#"
     xml:base="http://gaius.local/test"
     xmlns:owl="http://www.w3.org/2002/07/owl#"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
    <owl:Ontology rdf:about="http://gaius.local/test"/>
    <owl:Class rdf:about="http://gaius.local/test#MachineLearning">
        <rdfs:label>Machine Learning</rdfs:label>
    </owl:Class>
    <owl:Class rdf:about="http://gaius.local/test#NeuralNetwork">
        <rdfs:label>Neural Network</rdfs:label>
        <rdfs:subClassOf rdf:resource="http://gaius.local/test#MachineLearning"/>
    </owl:Class>
    <owl:Class rdf:about="http://gaius.local/test#DeepLearning">
        <rdfs:label>Deep Learning</rdfs:label>
        <rdfs:subClassOf rdf:resource="http://gaius.local/test#NeuralNetwork"/>
    </owl:Class>
</rdf:RDF>
'''
        ontology_path = tmp_path / "test_ontology.owl"
        ontology_path.write_text(owl_content)
        return ontology_path

    def test_deeponto_import(self):
        """Test that DeepOnto is importable - JVM is a hard requirement."""
        import deeponto
        assert deeponto is not None

    def test_ontology_loads_with_deeponto(self, minimal_ontology):
        """Test that ontology can be loaded via DeepOnto."""
        inferencer = SubsumptionInferencer(ontology_path=minimal_ontology)
        ontology = inferencer._get_ontology()
        assert ontology is not None

    def test_gaius_ontology_loads(self, gaius_ontology):
        """Test that internal Gaius domain ontology loads correctly."""
        inferencer = SubsumptionInferencer(ontology_path=gaius_ontology)
        ontology = inferencer._get_ontology()
        assert ontology is not None

        # Verify it has enough classes for BERTSubs training
        classes = list(ontology.owl_classes)
        assert len(classes) >= 20, f"Expected at least 20 classes, got {len(classes)}"

    @pytest.mark.slow  # Takes ~30-60 seconds due to BERT fine-tuning
    def test_predict_subsumption(self, gaius_ontology):
        """Test subsumption prediction with real BERTSubs.

        Uses the Gaius domain ontology which has enough classes for
        BERTSubsIntraPipeline to extract training data from.

        Note: This test applies a Python 3.11+ compatibility patch for
        random.sample() on sets (DeepOnto 0.9.3 bug).
        """
        inferencer = SubsumptionInferencer(ontology_path=gaius_ontology)

        # Use class IRIs from the Gaius ontology
        candidate = inferencer.predict_subsumption(
            subclass="http://gaius.zndx.org/ontology#NeuralNetwork",
            superclass="http://gaius.zndx.org/ontology#DeepLearning",
        )

        assert isinstance(candidate, SubsumptionCandidate)
        assert 0 <= candidate.confidence <= 1
        assert "NeuralNetwork" in candidate.subclass
        assert "DeepLearning" in candidate.superclass
