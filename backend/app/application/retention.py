"""What the backend may keep, under the Google terms decisions (plan §4, D2 and D6).

Decision D6: Google Routes distances and durations are not stored outside the request
that produced them. The matrix cache does not keep them (``RoutingService``), saved
scenarios drop them, and anything Version 1.0 stored is removed at start-up.
Matrices from JSON fixtures or the offline fake provider carry no such terms.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from backend.app.persistence.database import SQLiteDatabase
from backend.app.persistence.matrix_cache import SQLiteMatrixCache
from backend.app.persistence.scenario_repository import SQLiteScenarioRepository

LOGGER = logging.getLogger(__name__)

GOOGLE_MATRIX_SOURCE = "google_routes"
"""``GoogleRoutingProvider.provider_name``, stamped on every matrix it returns."""

UNSTORABLE_MATRIX_SOURCES = frozenset({GOOGLE_MATRIX_SOURCE})

JsonObject = dict[str, Any]


def matrix_is_storable(matrix: Any) -> bool:
    """Whether a matrix payload may be kept; Google matrices may not (D6)."""
    if not isinstance(matrix, Mapping):
        return True
    return str(matrix.get("source", "")) not in UNSTORABLE_MATRIX_SOURCES


def without_unstorable_matrix(payload: Mapping[str, Any]) -> tuple[JsonObject, bool]:
    """The payload without an embedded Google matrix, and whether one was removed."""
    copied = deepcopy(dict(payload))
    matrix = copied.get("routing_matrix")
    if matrix is not None and not matrix_is_storable(matrix):
        del copied["routing_matrix"]
        return copied, True
    return copied, False


@dataclass(frozen=True, slots=True)
class RetentionSweep:
    """What the start-up sweep removed."""

    cached_matrices_removed: int
    scenarios_cleaned: int


def sweep_unstorable_matrices(database: SQLiteDatabase) -> RetentionSweep:
    """Remove Google matrices from the matrix cache and from saved scenarios."""
    cache = SQLiteMatrixCache(database)
    removed = sum(cache.purge_source(source) for source in sorted(UNSTORABLE_MATRIX_SOURCES))
    cleaned = SQLiteScenarioRepository(database).rewrite_payloads(_strip_for_sweep)
    if removed or cleaned:
        LOGGER.info(
            "Removed %s cached Google matrices and Google matrices from %s saved scenarios",
            removed,
            cleaned,
        )
    return RetentionSweep(cached_matrices_removed=removed, scenarios_cleaned=cleaned)


def _strip_for_sweep(payload: JsonObject) -> JsonObject | None:
    stripped, removed = without_unstorable_matrix(payload)
    return stripped if removed else None
