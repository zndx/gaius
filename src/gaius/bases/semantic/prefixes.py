"""Standard ontology prefixes for semantic layer.

Provides well-known prefix mappings for ontology IRIs used in Bases.
BFO (Basic Formal Ontology) is the upper ontology for domain grounding.

BFO Reference:
    https://basic-formal-ontology.org/
    https://github.com/BFO-ontology/BFO-2020

OBO Foundry:
    https://obofoundry.org/
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class OntologyPrefix:
    """A prefix mapping for ontology IRIs.

    Example:
        OntologyPrefix("BFO", "http://purl.obolibrary.org/obo/BFO_")
        # Maps "BFO:0000040" to "http://purl.obolibrary.org/obo/BFO_0000040"
    """

    prefix: str
    iri_base: str
    description: str = ""


# Standard ontology prefixes
# These are always available in @context

BFO = OntologyPrefix(
    prefix="BFO",
    iri_base="http://purl.obolibrary.org/obo/BFO_",
    description="Basic Formal Ontology - upper ontology for scientific domains",
)

OBO = OntologyPrefix(
    prefix="obo",
    iri_base="http://purl.obolibrary.org/obo/",
    description="OBO Foundry - open biological/biomedical ontologies",
)

RDF = OntologyPrefix(
    prefix="rdf",
    iri_base="http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    description="RDF syntax namespace",
)

RDFS = OntologyPrefix(
    prefix="rdfs",
    iri_base="http://www.w3.org/2000/01/rdf-schema#",
    description="RDF Schema namespace",
)

XSD = OntologyPrefix(
    prefix="xsd",
    iri_base="http://www.w3.org/2001/XMLSchema#",
    description="XML Schema datatypes",
)

OWL = OntologyPrefix(
    prefix="owl",
    iri_base="http://www.w3.org/2002/07/owl#",
    description="OWL Web Ontology Language",
)

DC = OntologyPrefix(
    prefix="dc",
    iri_base="http://purl.org/dc/elements/1.1/",
    description="Dublin Core metadata elements",
)

DCT = OntologyPrefix(
    prefix="dct",
    iri_base="http://purl.org/dc/terms/",
    description="Dublin Core terms",
)

SKOS = OntologyPrefix(
    prefix="skos",
    iri_base="http://www.w3.org/2004/02/skos/core#",
    description="Simple Knowledge Organization System",
)

SCHEMA = OntologyPrefix(
    prefix="schema",
    iri_base="https://schema.org/",
    description="Schema.org vocabulary",
)

# Gaius-specific namespace for local terms
GAIUS = OntologyPrefix(
    prefix="gaius",
    iri_base="https://gaius.zndx.dev/ontology/",
    description="Gaius local ontology namespace",
)


# BFO 2020 commonly used classes
# These are the OBO IDs for BFO classes

class BFOClasses:
    """BFO 2020 class IRIs for common concepts.

    BFO distinguishes between:
    - Continuants: entities that persist through time (objects, qualities)
    - Occurrents: entities that unfold in time (processes, events)

    Reference: https://basic-formal-ontology.org/bfo-2020.html
    """

    # Independent Continuants (things that exist independently)
    MATERIAL_ENTITY = "BFO:0000040"  # Physical objects
    OBJECT = "BFO:0000030"  # Bounded material entity
    OBJECT_AGGREGATE = "BFO:0000027"  # Collection of objects
    FIAT_OBJECT_PART = "BFO:0000024"  # Part demarcated by fiat

    # Dependent Continuants (qualities, roles, dispositions)
    QUALITY = "BFO:0000019"  # Inheres in independent continuant
    RELATIONAL_QUALITY = "BFO:0000145"  # Quality involving multiple entities
    ROLE = "BFO:0000023"  # Externally grounded realizable
    DISPOSITION = "BFO:0000016"  # Internally grounded realizable
    FUNCTION = "BFO:0000034"  # Selected-for disposition

    # Spatial regions
    SPATIAL_REGION = "BFO:0000006"
    ONE_D_SPATIAL_REGION = "BFO:0000026"
    TWO_D_SPATIAL_REGION = "BFO:0000009"
    THREE_D_SPATIAL_REGION = "BFO:0000028"
    SITE = "BFO:0000029"  # 3D region of a material entity

    # Temporal regions
    TEMPORAL_REGION = "BFO:0000008"
    ZERO_D_TEMPORAL_REGION = "BFO:0000148"  # Instant
    ONE_D_TEMPORAL_REGION = "BFO:0000038"  # Interval

    # Occurrents (processes, events)
    PROCESS = "BFO:0000015"  # Occurrent with temporal parts
    PROCESS_BOUNDARY = "BFO:0000035"  # Instant boundary of process
    HISTORY = "BFO:0000182"  # Sum of processes of a continuant

    # Relations (object properties)
    PARTICIPATES_IN = "BFO:0000056"  # Continuant participates in process
    HAS_PARTICIPANT = "BFO:0000057"  # Process has participant
    LOCATED_IN = "BFO:0000171"  # Spatial location
    LOCATED_IN_AT = "BFO:0000124"  # Located in at time
    OCCURS_IN = "BFO:0000066"  # Process occurs in site
    PART_OF = "BFO:0000050"  # Parthood
    HAS_PART = "BFO:0000051"


# Convenient BFO term aliases for use in queries
# Maps human-readable names to BFO IRIs
BFO_ALIASES: dict[str, str] = {
    # Continuants
    "material_entity": BFOClasses.MATERIAL_ENTITY,
    "object": BFOClasses.OBJECT,
    "quality": BFOClasses.QUALITY,
    "role": BFOClasses.ROLE,
    "disposition": BFOClasses.DISPOSITION,
    "function": BFOClasses.FUNCTION,
    "site": BFOClasses.SITE,
    # Temporal
    "temporal_region": BFOClasses.TEMPORAL_REGION,
    "instant": BFOClasses.ZERO_D_TEMPORAL_REGION,
    "interval": BFOClasses.ONE_D_TEMPORAL_REGION,
    # Occurrents
    "process": BFOClasses.PROCESS,
    "history": BFOClasses.HISTORY,
    # Relations
    "participates_in": BFOClasses.PARTICIPATES_IN,
    "has_participant": BFOClasses.HAS_PARTICIPANT,
    "located_in": BFOClasses.LOCATED_IN,
    "occurs_in": BFOClasses.OCCURS_IN,
    "part_of": BFOClasses.PART_OF,
    "has_part": BFOClasses.HAS_PART,
}


# Default prefixes available in all @context
DEFAULT_PREFIXES: dict[str, str] = {
    BFO.prefix: BFO.iri_base,
    OBO.prefix: OBO.iri_base,
    RDF.prefix: RDF.iri_base,
    RDFS.prefix: RDFS.iri_base,
    XSD.prefix: XSD.iri_base,
    OWL.prefix: OWL.iri_base,
    SKOS.prefix: SKOS.iri_base,
    SCHEMA.prefix: SCHEMA.iri_base,
    GAIUS.prefix: GAIUS.iri_base,
}


def expand_curie(curie: str, prefixes: dict[str, str] | None = None) -> str:
    """Expand a CURIE (Compact URI) to a full IRI.

    Args:
        curie: CURIE like "BFO:0000040" or "schema:Person"
        prefixes: Prefix mappings (defaults to DEFAULT_PREFIXES)

    Returns:
        Full IRI like "http://purl.obolibrary.org/obo/BFO_0000040"

    Raises:
        ValueError: If prefix is unknown
    """
    if prefixes is None:
        prefixes = DEFAULT_PREFIXES

    if ":" not in curie:
        return curie  # Already a full IRI or local name

    prefix, local = curie.split(":", 1)

    # Check BFO aliases first
    if prefix == "BFO" and local in BFO_ALIASES:
        return expand_curie(BFO_ALIASES[local], prefixes)

    if prefix in prefixes:
        return prefixes[prefix] + local

    raise ValueError(f"Unknown prefix: {prefix}")


def compact_iri(iri: str, prefixes: dict[str, str] | None = None) -> str:
    """Compact a full IRI to a CURIE if possible.

    Args:
        iri: Full IRI like "http://purl.obolibrary.org/obo/BFO_0000040"
        prefixes: Prefix mappings (defaults to DEFAULT_PREFIXES)

    Returns:
        CURIE like "BFO:0000040" or original IRI if no match
    """
    if prefixes is None:
        prefixes = DEFAULT_PREFIXES

    for prefix, base in prefixes.items():
        if iri.startswith(base):
            local = iri[len(base):]
            return f"{prefix}:{local}"

    return iri
