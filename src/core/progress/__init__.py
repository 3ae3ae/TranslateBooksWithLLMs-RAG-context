"""Unified progress domain model for the translation/refine pipeline.

This package defines the single source of truth for progress reporting:

* :class:`Phase` — the coarse phase of work (translating vs refining).
* :class:`ProgressSnapshot` — an immutable, serializable view of progress at
  a point in time. ``percent`` is the *global* 0–100 value the UI displays;
  no consumer recomputes it.

In production the percent authority is reached through the
:func:`snapshot_from_legacy_stats` bridge: the format engines still emit their
historical stats dicts, and the bridge maps them onto a single canonical
``percent`` / ``phase`` at the handler seam (``src/api/handlers.py``).
"""

from .legacy import snapshot_from_legacy_stats
from .snapshot import Phase, ProgressSnapshot, global_percent

__all__ = [
    "Phase",
    "ProgressSnapshot",
    "global_percent",
    "snapshot_from_legacy_stats",
]
