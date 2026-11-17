"""Pure address-provenance rules shared by validation and address resolution.

A geocoded location carries a fingerprint of the address text (and the region bias)
that produced its coordinates. The fingerprint is self-describing,
``v1:<region>:<sha256>``, so validation can tell whether the coordinates still
belong to the current address without knowing which region the resolver used.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta

GEOCODE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
"""Google allows geocoded coordinates to be cached for at most 30 consecutive days."""

FINGERPRINT_VERSION = "v1"
_NO_REGION = "-"
_REGION_PATTERN = re.compile(r"^[a-z]{2}$")
_FINGERPRINT_PATTERN = re.compile(r"^v1:(?P<region>[a-z]{2}|-):(?P<digest>[0-9a-f]{64})$")
_EARTH_RADIUS_KM = 6_371.0088


def normalize_address(address: str) -> str:
    """Collapse whitespace and case so trivially different spellings share one lookup."""
    return " ".join(address.strip().split()).casefold()


def normalize_region_code(region_code: str | None) -> str | None:
    """Return a lower-case two-letter region code, or ``None`` for no region bias."""
    if region_code is None:
        return None
    value = region_code.strip().lower()
    if not value:
        return None
    if not _REGION_PATTERN.fullmatch(value):
        raise ValueError("region code must be two letters, such as 'ca'")
    return value


def address_fingerprint(address: str, region_code: str | None) -> str:
    """Return the provenance fingerprint for an address and region bias."""
    normalized = normalize_address(address)
    if not normalized:
        raise ValueError("address cannot be empty")
    region = normalize_region_code(region_code) or _NO_REGION
    digest = hashlib.sha256(f"{FINGERPRINT_VERSION}\n{region}\n{normalized}".encode()).hexdigest()
    return f"{FINGERPRINT_VERSION}:{region}:{digest}"


def fingerprint_matches_address(fingerprint: str, address: str) -> bool:
    """Whether a stored fingerprint was produced from this address text.

    An unrecognised fingerprint never matches, so coordinates of unknown provenance
    are treated as stale rather than trusted.
    """
    match = _FINGERPRINT_PATTERN.fullmatch(fingerprint.strip())
    if match is None or not normalize_address(address):
        return False
    region = match.group("region")
    return address_fingerprint(address, None if region == _NO_REGION else region) == (
        fingerprint.strip()
    )


def geocode_is_expired(
    geocoded_at: datetime,
    now: datetime,
    max_age_seconds: int = GEOCODE_MAX_AGE_SECONDS,
) -> bool:
    """Whether coordinates fetched at ``geocoded_at`` are past the retention limit."""
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    return now - geocoded_at >= timedelta(seconds=max_age_seconds)


def straight_line_distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Great-circle distance, used only as a sanity check, never as a routing cost."""
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(haversine)))
