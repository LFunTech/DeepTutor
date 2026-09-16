"""Immersive reading engine — materials, locators, annotations, export.

A *material* is a file the user reads: it is cut once into **units** and stored
per-unit, so every later operation addresses it by **locator** (a 1-indexed unit
number that means page / chapter / slide / section depending on the format).
That one abstraction is what lets a model cite "page 12" and the reader scroll
to page 12 without either side knowing the file is a PDF.

Layering, bottom-up — each layer depends only on the ones above it in this list:

* :mod:`.models` — dataclasses and errors. No I/O, no imports from siblings.
* :mod:`.extract` — file → units. The only module that knows about formats.
* :mod:`.search` — pure locator-addressed matching over ``(locator, text)``.
* :mod:`.store` — durable per-material layout, atomic writes, annotations.
* :mod:`.service` — the composition callers use (read / search / outline /
  quote verification).
* :mod:`.export` — the annotated artefacts a user can take away.

Nothing here imports the chat loop, the tool registry or FastAPI, so the engine
is testable on its own and the capability that drives it
(:mod:`deeptutor.capabilities.reading`) stays a thin shell.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "IngestionStatus": "deeptutor.reading.catalog_models",
    "MaterialRecord": "deeptutor.reading.catalog_models",
    "ReadingSessionRecord": "deeptutor.reading.catalog_models",
    "SourceKind": "deeptutor.reading.catalog_models",
    "WorkspaceRecord": "deeptutor.reading.catalog_models",
    "WorkspaceTab": "deeptutor.reading.catalog_models",
    "ReadingCatalogStore": "deeptutor.reading.catalog_store",
    "create_epub_pairing": "deeptutor.reading.epub_bilingual",
    "delete_epub_pairing": "deeptutor.reading.epub_bilingual",
    "list_epub_pairings": "deeptutor.reading.epub_bilingual",
    "recommend_epub_candidates": "deeptutor.reading.epub_bilingual",
    "ExportFormat": "deeptutor.reading.export",
    "ExportResult": "deeptutor.reading.export",
    "export_material": "deeptutor.reading.export",
    "Extraction": "deeptutor.reading.extract",
    "extract_material": "deeptutor.reading.extract",
    "ANNOTATION_COLORS": "deeptutor.reading.models",
    "Annotation": "deeptutor.reading.models",
    "AnnotationKind": "deeptutor.reading.models",
    "MaterialManifest": "deeptutor.reading.models",
    "MaterialNotFound": "deeptutor.reading.models",
    "OutlineEntry": "deeptutor.reading.models",
    "ReadingBookmark": "deeptutor.reading.models",
    "ReadingError": "deeptutor.reading.models",
    "ReadingPosition": "deeptutor.reading.models",
    "ReadingUpgradeConflict": "deeptutor.reading.models",
    "Rect": "deeptutor.reading.models",
    "RenderMode": "deeptutor.reading.models",
    "SearchHit": "deeptutor.reading.models",
    "TextPositionSelector": "deeptutor.reading.models",
    "TextQuoteSelector": "deeptutor.reading.models",
    "TextSelector": "deeptutor.reading.models",
    "UnitKind": "deeptutor.reading.models",
    "UnitReference": "deeptutor.reading.models",
    "SearchResult": "deeptutor.reading.search",
    "search_units": "deeptutor.reading.search",
    "QuoteCheck": "deeptutor.reading.service",
    "RenderedUnits": "deeptutor.reading.service",
    "material_summary": "deeptutor.reading.service",
    "parse_locators": "deeptutor.reading.service",
    "render_outline": "deeptutor.reading.service",
    "render_units": "deeptutor.reading.service",
    "search_material": "deeptutor.reading.service",
    "unit_timestamps": "deeptutor.reading.service",
    "verify_quote": "deeptutor.reading.service",
    "ReadingStore": "deeptutor.reading.store",
    "content_hash": "deeptutor.reading.store",
}


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


__all__ = [
    "ANNOTATION_COLORS",
    "Annotation",
    "AnnotationKind",
    "ExportFormat",
    "ExportResult",
    "Extraction",
    "IngestionStatus",
    "MaterialRecord",
    "MaterialManifest",
    "MaterialNotFound",
    "OutlineEntry",
    "QuoteCheck",
    "ReadingError",
    "ReadingCatalogStore",
    "ReadingBookmark",
    "ReadingPosition",
    "ReadingSessionRecord",
    "ReadingUpgradeConflict",
    "ReadingStore",
    "Rect",
    "RenderedUnits",
    "SearchHit",
    "SearchResult",
    "SourceKind",
    "RenderMode",
    "TextPositionSelector",
    "TextQuoteSelector",
    "TextSelector",
    "UnitKind",
    "UnitReference",
    "WorkspaceRecord",
    "WorkspaceTab",
    "content_hash",
    "create_epub_pairing",
    "delete_epub_pairing",
    "export_material",
    "extract_material",
    "list_epub_pairings",
    "material_summary",
    "parse_locators",
    "render_outline",
    "recommend_epub_candidates",
    "render_units",
    "unit_timestamps",
    "search_material",
    "search_units",
    "verify_quote",
]
