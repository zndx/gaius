"""HermiT-certified OWL TBox for Theta consolidation.

SKOS is terminology grounded to this ontology. CLT is a content graph.
Neither is the TBox. Do not mint owl:Class from thoughts or markdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GURU_MISSING = (
    "#THETA.00000004.ONTOLOGY_MISSING HermiT-certified sdg-ontology.owl is not in this checkout.\n"
    "  Try: git submodule update --init external/sdg-corpora"
)

_REPO = Path(__file__).resolve().parents[4]
CERTIFIED_OWL = _REPO / "external" / "sdg-corpora" / "ontology" / "sdg-ontology.owl"

_SKIP_IRI_FRAGMENTS = ("Nothing", "Thing")


@dataclass(frozen=True)
class ClassVerbalization:
    iri: str
    label: str
    retrieval_text: str
    depth: int


CCO_IRI = "https://signals.zndx.org/sdg/imports/cco-module"


def ontology_for_owlready(path: Path) -> Path:
    """RDF/XML owlready2 can load: CCO is local, property/class puns dropped.

    The certified OWL puns some object properties as classes (``bindsProvider``).
    owlready2 refuses that. DeepOnto keeps the original file.
    """
    from rdflib import Graph, Namespace

    src = Path(path)
    cache = src.parent / ".owlready" / f"{src.stem}.nopun.owl"
    cco_xml = src.parent / ".owlready" / "cco-module"
    ttl = src.parent / "imports" / "cco-module.ttl"
    if (
        cache.is_file()
        and cco_xml.is_file()
        and cache.stat().st_mtime >= src.stat().st_mtime
        and (not ttl.is_file() or cco_xml.stat().st_mtime >= ttl.stat().st_mtime)
    ):
        from owlready2 import onto_path

        folder = str(cco_xml.parent)
        if folder not in onto_path:
            onto_path.insert(0, folder)
        return cache
    cache.parent.mkdir(exist_ok=True)
    if ttl.is_file():
        cco = Graph()
        cco.parse(ttl, format="turtle")
        cco.serialize(destination=cco_xml, format="xml")
    graph = Graph()
    graph.parse(src, format="xml")
    OWL = Namespace("http://www.w3.org/2002/07/owl#")
    RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
    props = set(graph.subjects(RDF.type, OWL.ObjectProperty)) | set(
        graph.subjects(RDF.type, OWL.DatatypeProperty)
    )
    for prop in props:
        graph.remove((prop, RDF.type, OWL.Class))
        graph.remove((prop, RDFS.subClassOf, None))
    graph.serialize(destination=cache, format="xml")
    from owlready2 import onto_path

    folder = str(cache.parent)
    if folder not in onto_path:
        onto_path.insert(0, folder)
    return cache


def load_pinned_imports() -> None:
    """Put CCO on owlready2's onto_path so the import IRI is not fetched.

    owlready2 looks up the IRI tail (``cco-module``) and only parses RDF/XML.
    The pin is Turtle, so write a sibling RDF/XML cache once.
    """
    from owlready2 import onto_path
    from rdflib import Graph

    ttl = CERTIFIED_OWL.parent / "imports" / "cco-module.ttl"
    if not ttl.is_file():
        return
    cache = ttl.parent / ".owlready"
    cache.mkdir(exist_ok=True)
    xml = cache / "cco-module"
    if not xml.is_file() or xml.stat().st_mtime < ttl.stat().st_mtime:
        graph = Graph()
        graph.parse(ttl, format="turtle")
        graph.serialize(destination=xml, format="xml")
    folder = str(cache)
    if folder not in onto_path:
        onto_path.insert(0, folder)


def certified_ontology_path() -> Path:
    """Path to the HermiT-certified SDG OWL. Fail if the corpora pin is absent."""
    if not CERTIFIED_OWL.is_file():
        raise FileNotFoundError(GURU_MISSING)
    return CERTIFIED_OWL


def _local(iri: str) -> str:
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    return iri.rstrip("/").rsplit("/", 1)[-1]


def _skip(iri: str) -> bool:
    loc = _local(iri)
    return loc in _SKIP_IRI_FRAGMENTS or iri.endswith("#Thing") or iri.endswith("#Nothing")


def _label_of(cls: object) -> str:
    labs = list(getattr(cls, "label", []) or [])
    if labs:
        return str(labs[0])
    return _local(str(getattr(cls, "iri", "")))


def _retrieval_text(cls: object, label: str) -> str:
    comments = [str(c) for c in (getattr(cls, "comment", []) or []) if str(c).strip()]
    defs = []
    for name in ("IAO_0000115",):
        vals = getattr(cls, name, None)
        if vals:
            defs.extend(str(v) for v in vals if str(v).strip())
    extra = " ".join(defs or comments[:1])
    return f"{label}. {extra}".strip() if extra else label


@lru_cache(maxsize=2)
def tbox_relations(path: str) -> tuple[tuple[ClassVerbalization, ...], frozenset[tuple[str, str]]]:
    """Named classes and entailed (subclass, superclass) IRIs.

    Entailment is the asserted ``rdfs:subClassOf`` transitive closure
    (owlready2 ancestors). Direct and ancestral ⊑ are both excluded from
    BERTSubs candidates.
    """
    from owlready2 import Thing, get_ontology

    load_pinned_imports()
    ready = ontology_for_owlready(Path(path))
    onto = get_ontology(ready.resolve().as_uri()).load()
    classes = [c for c in onto.classes() if getattr(c, "iri", None) and not _skip(c.iri)]
    records: list[ClassVerbalization] = []
    entailed: set[tuple[str, str]] = set()
    for cls in classes:
        ancs = [
            a
            for a in cls.ancestors()
            if a is not cls and a is not Thing and getattr(a, "iri", None) and not _skip(a.iri)
        ]
        depth = len(ancs)
        for a in ancs:
            entailed.add((cls.iri, a.iri))
        for parent in cls.is_a:
            if getattr(parent, "iri", None) and parent.iri != cls.iri and not _skip(parent.iri):
                entailed.add((cls.iri, parent.iri))
        label = _label_of(cls)
        records.append(
            ClassVerbalization(
                iri=cls.iri,
                label=label,
                retrieval_text=_retrieval_text(cls, label),
                depth=depth,
            )
        )
    return tuple(records), frozenset(entailed)


def class_verbalizations(path: Path | None = None) -> tuple[ClassVerbalization, ...]:
    p = path or certified_ontology_path()
    records, _ = tbox_relations(str(p))
    return records


def entailed_subsumptions(path: Path | None = None) -> frozenset[tuple[str, str]]:
    p = path or certified_ontology_path()
    _, entailed = tbox_relations(str(p))
    return entailed
