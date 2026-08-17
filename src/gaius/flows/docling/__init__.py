"""Docling flow package - PDF→markdown conversion.

Two modes (auto-detected from the URL): arXiv papers become KB zettelkasten
notes; any other PDF URL is converted and written into a local output_dir.
"""

from gaius.flows.docling.flow import ArxivDoclingFlow

__all__ = ["ArxivDoclingFlow"]
