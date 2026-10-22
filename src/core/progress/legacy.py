"""Bridge from the legacy ad-hoc stats dicts to the unified snapshot.

This is the production seam for canonical progress. The format engines emit
their three historical shapes (the bare ``{total,completed,failed}`` dict, the
rich ``TranslationMetrics`` dict, and the token-tracker dict); the handler
(``src/api/handlers.py``) tags each emit with the workflow phase and passes the
merged dict here. This function turns it into a :class:`ProgressSnapshot` so a
single canonical ``percent`` / ``phase`` is emitted alongside the legacy fields
and displayed by the frontend verbatim.

"""

from __future__ import annotations

from typing import Any, Dict

from .snapshot import Phase, ProgressSnapshot, global_percent

_REFINE_SPLIT = 50.0


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def snapshot_from_legacy_stats(stats: Dict[str, Any]) -> ProgressSnapshot:
    """Derive a :class:`ProgressSnapshot` from a merged legacy stats dict."""
    total = _as_int(stats.get("total_chunks"))
    done = _as_int(stats.get("completed_chunks"))
    failed = _as_int(stats.get("failed_chunks"))
    enable_refinement = bool(stats.get("enable_refinement"))
    refine_only = bool(stats.get("refine_only"))
    phase_num = stats.get("current_phase") or 1

    if stats.get('interleaved'):
        phase = Phase.NOTES if stats.get('phase') == 'notes' else Phase.REFINING if stats.get('phase') in ('polishing', 'refining') else Phase.TRANSLATING
        steps = _as_int(stats.get('translated_chunks')) + _as_int(stats.get('polished_chunks'))
        percent = min(100.0, 100.0 * steps / (2 * total)) if total else 0.0
        refinement_enabled = True
    elif enable_refinement:
        # Two-phase refine-after: translation in [0, 50], refinement in [50, 100].
        phase = Phase.REFINING if phase_num == 2 else Phase.TRANSLATING
        percent = global_percent(phase, done, total, True, _REFINE_SPLIT)
        refinement_enabled = True
    else:
        phase = Phase.REFINING if refine_only else Phase.TRANSLATING
        progress_percent = stats.get("progress_percent")
        # Mirror the frontend: a single-phase run trusts a server-sent
        # progress_percent when present, else falls back to chunk ratio.
        if isinstance(progress_percent, (int, float)) and not isinstance(
            progress_percent, bool
        ):
            percent = min(max(float(progress_percent), 0.0), 100.0)
        else:
            percent = global_percent(phase, done, total, False)
        refinement_enabled = False

    succeeded = max(0, done - failed)
    return ProgressSnapshot(
        phase=phase,
        units_done=done,
        units_total=total,
        units_succeeded=succeeded,
        units_failed=failed,
        percent=percent,
        refinement_enabled=refinement_enabled,
    )
