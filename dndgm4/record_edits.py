"""Atomic saves for an editor opened against one immutable library baseline."""
from __future__ import annotations

from .models import Creature


def save_reviewed_record(repository, baseline: Creature, candidate: Creature) -> Creature:
    """Refuse stale edits under the same write lock used to commit the change.

    The caller retains the editor and its draft on failure, then offers a reload
    or cancellation. New records use the normal library creation path.
    """
    if not isinstance(baseline, Creature) or not isinstance(candidate, Creature) or not baseline.id:
        raise ValueError("Choose the saved record that this edit was opened from.")
    if any(getattr(candidate, field) != getattr(baseline, field)
           for field in ("id", "created_at", "updated_at")):
        raise ValueError("An edit cannot change the original record identity or timestamps.")
    return repository.save_if_unchanged(candidate, baseline)
