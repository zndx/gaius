"""Semantic layer for ontology-grounded queries.

Provides BFO ontology grounding via @context and Data Element semantics
for dependent field validation.

@context Example:
    from gaius.bases.semantic import OntologyContext

    ctx = OntologyContext.from_dict({
        "@vocab": "https://gaius.zndx.dev/ontology/",
        "entity_id": {"@id": "BFO:0000040", "@type": "STRING"},
        "site": "BFO:site",
        "event_time": {"@id": "BFO:temporal_region", "@type": "UNIXTIME_MICROS"},
    })

    # Resolve term to column
    column = ctx.resolve_term("BFO:site")  # Returns "site"

    # Resolve column to term
    iri = ctx.resolve_column("entity_id")  # Returns "BFO:0000040"

Data Element Example:
    from gaius.bases.semantic import DataElement, ValueConstraint

    diagnosis = DataElement(
        name="diagnosis_code",
        term_iri="obo:OGMS_0000073",
        kudu_type="STRING",
        depends_on=["coding_system"],
        constraints=[
            ValueConstraint(
                when={"coding_system": "ICD10"},
                pattern=r"^[A-Z][0-9]{2}(\\.[0-9]{1,4})?$"
            ),
        ],
    )

BFO Prefixes:
    from gaius.bases.semantic import BFO, BFOClasses, expand_curie

    # Expand CURIE to full IRI
    expand_curie("BFO:0000040")
    # Returns: "http://purl.obolibrary.org/obo/BFO_0000040"

    # Use BFO class constants
    material_entity = BFOClasses.MATERIAL_ENTITY  # "BFO:0000040"
"""

# Prefixes and BFO
from gaius.bases.semantic.prefixes import (
    OntologyPrefix,
    BFO,
    OBO,
    RDF,
    RDFS,
    XSD,
    OWL,
    DC,
    DCT,
    SKOS,
    SCHEMA,
    GAIUS,
    BFOClasses,
    BFO_ALIASES,
    DEFAULT_PREFIXES,
    expand_curie,
    compact_iri,
)

# Context
from gaius.bases.semantic.context import (
    OntologyContext,
    TermMapping,
    TermResolutionError,
)

# Data Elements
from gaius.bases.semantic.data_element import (
    DataElement,
    DataElementSchema,
    ValueConstraint,
)

__all__ = [
    # Prefixes
    "OntologyPrefix",
    "BFO",
    "OBO",
    "RDF",
    "RDFS",
    "XSD",
    "OWL",
    "DC",
    "DCT",
    "SKOS",
    "SCHEMA",
    "GAIUS",
    "BFOClasses",
    "BFO_ALIASES",
    "DEFAULT_PREFIXES",
    "expand_curie",
    "compact_iri",
    # Context
    "OntologyContext",
    "TermMapping",
    "TermResolutionError",
    # Data Elements
    "DataElement",
    "DataElementSchema",
    "ValueConstraint",
]
