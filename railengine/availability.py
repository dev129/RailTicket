"""Parsing / normalization of raw IRCTC-style availability strings.

The live API (and the mock, deliberately) returns human-readable status
strings such as ``AVAILABLE-0023``, ``RAC 12``, ``GNWL 134/WL 120``,
``CURR_AVBL-0005``, ``REGRET/WL``. Every engine above this layer works on
the normalized :class:`AvailabilityStatus` only, so swapping data sources
never touches engine logic.
"""

from __future__ import annotations

import re

from .models import AvailabilityStatus, StatusState

# Ordered (pattern -> builder). First match wins.
_FIRST_INT = re.compile(r"(\d+)")


def _first_int(s: str) -> int:
    m = _FIRST_INT.search(s)
    return int(m.group(1)) if m else 0


def parse_status(raw: str) -> AvailabilityStatus:
    """Normalize one raw provider string into an :class:`AvailabilityStatus`.

    Unknown / unparseable strings degrade to ``NOT_AVAILABLE`` rather than
    raising, so a single odd response never breaks a scan.
    """
    if raw is None:
        return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, "")

    s = raw.strip().upper()
    if not s:
        return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, raw)

    # Train gone / chart prepared with no current quota.
    if "DEPARTED" in s or "TRAIN DEPARTED" in s:
        return AvailabilityStatus(StatusState.DEPARTED, 0, raw)

    # Current (post-charting) availability.
    if "CURR_AVBL" in s or "CURR AVBL" in s:
        return AvailabilityStatus(StatusState.CURR_AVBL, _first_int(s), raw)

    # Plain confirmed availability.
    if s.startswith("AVAILABLE") or s.startswith("AVBL") or s.startswith("AVL"):
        return AvailabilityStatus(StatusState.AVAILABLE, _first_int(s), raw)

    # RAC.
    if s.startswith("RAC"):
        return AvailabilityStatus(StatusState.RAC, _first_int(s), raw)

    # Regret / no booking (check before generic WL so "REGRET/WL" is regret).
    if "REGRET" in s or "NOT AVAILABLE" in s:
        if "REGRET" in s:
            return AvailabilityStatus(StatusState.REGRET, 0, raw)
        return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, raw)

    # Any waitlist family: GNWL / RLWL / PQWL / RSWL / TQWL / WL.
    # Depth is the *first* number, e.g. "GNWL 134/WL 120" -> 134 current depth.
    if "WL" in s:
        return AvailabilityStatus(StatusState.WAITLIST, _first_int(s), raw)

    return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, raw)
