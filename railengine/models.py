"""Core domain model for the rail-journey engine.

Design notes
------------
A train is an *ordered sequence of stops*, and seats are *segment-based*
inventory: a reservation occupies a berth over a half-open span
``[board_seq, alight_seq)`` of the route. That single fact drives both
features (see README).

Everything the engines consume is normalized here so that the availability
data source (live API vs. mock) is fully interchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from enum import Enum
from typing import Optional


# --------------------------------------------------------------------------- #
# Travel classes
# --------------------------------------------------------------------------- #
class TravelClass(str, Enum):
    """Reserved classes, ordered from cheapest to most premium."""

    SL = "SL"      # Sleeper
    E3 = "3E"      # AC 3-tier economy
    A3 = "3A"      # AC 3-tier
    A2 = "2A"      # AC 2-tier
    A1 = "1A"      # AC first class

    @property
    def label(self) -> str:
        return {
            "SL": "Sleeper",
            "3E": "AC 3 Economy",
            "3A": "AC 3-Tier",
            "2A": "AC 2-Tier",
            "1A": "AC First",
        }[self.value]


# --------------------------------------------------------------------------- #
# Static timetable entities
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Station:
    code: str              # e.g. "JP"
    name: str              # e.g. "Jaipur Jn"


@dataclass(frozen=True)
class TrainStop:
    """One row of a train's schedule."""

    station: str           # station code
    seq: int               # 0-based position along the route
    arr: Optional[str]     # "HH:MM" local, None at origin
    dep: Optional[str]     # "HH:MM" local, None at destination
    day_offset: int        # days since journey start (0, 1, ...)
    dist_km: int           # cumulative distance from origin


@dataclass(frozen=True)
class Train:
    number: str
    name: str
    stops: tuple[TrainStop, ...]
    classes: tuple[TravelClass, ...]

    # --- route helpers ----------------------------------------------------- #
    def seq_of(self, station_code: str) -> int:
        for s in self.stops:
            if s.station == station_code:
                return s.seq
        raise KeyError(f"{station_code} not on train {self.number}")

    def stop_at_seq(self, seq: int) -> TrainStop:
        return self.stops[seq]

    def serves(self, origin: str, dest: str) -> bool:
        try:
            return self.seq_of(origin) < self.seq_of(dest)
        except KeyError:
            return False

    def dist_between(self, from_seq: int, to_seq: int) -> int:
        return self.stops[to_seq].dist_km - self.stops[from_seq].dist_km


# --------------------------------------------------------------------------- #
# Normalized availability (what every provider must speak)
# --------------------------------------------------------------------------- #
class StatusState(str, Enum):
    """Canonical availability states, ordered best -> worst by `rank`."""

    AVAILABLE = "AVAILABLE"           # confirmed berth free now
    CURR_AVBL = "CURR_AVBL"           # current (post-charting) availability
    RAC = "RAC"                       # reservation against cancellation
    WAITLIST = "WAITLIST"             # WL / GNWL / RLWL / PQWL / TQWL ...
    REGRET = "REGRET"                 # no further booking
    NOT_AVAILABLE = "NOT_AVAILABLE"   # class/segment not offered
    DEPARTED = "DEPARTED"             # train gone / chart prepared, no quota

    @property
    def rank(self) -> int:
        order = [
            StatusState.AVAILABLE,
            StatusState.CURR_AVBL,
            StatusState.RAC,
            StatusState.WAITLIST,
            StatusState.REGRET,
            StatusState.NOT_AVAILABLE,
            StatusState.DEPARTED,
        ]
        return order.index(self)

    @property
    def confirmable(self) -> bool:
        """Can a passenger realistically travel confirmed on this?"""
        return self in (StatusState.AVAILABLE, StatusState.CURR_AVBL, StatusState.RAC)


@dataclass(frozen=True)
class AvailabilityStatus:
    """Normalized result of one availability query."""

    state: StatusState
    number: int = 0          # berths available (>=0) or WL depth (>0)
    raw: str = ""            # original provider string, for transparency

    @property
    def confirmable(self) -> bool:
        return self.state.confirmable

    def __str__(self) -> str:
        if self.state in (StatusState.AVAILABLE, StatusState.CURR_AVBL):
            return f"AVBL {self.number}"
        if self.state is StatusState.RAC:
            return f"RAC {self.number}"
        if self.state is StatusState.WAITLIST:
            return f"WL {self.number}"
        return self.state.value


# --------------------------------------------------------------------------- #
# Query + result value objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SegmentQuery:
    train_no: str
    travel_date: Date
    from_code: str
    to_code: str
    travel_class: TravelClass


@dataclass
class SegmentOption:
    """One candidate boarding/alighting option for 'next available seat'."""

    train_no: str
    travel_class: TravelClass
    from_code: str
    to_code: str
    from_seq: int
    to_seq: int
    status: AvailabilityStatus
    coverage: float                 # fraction of intended O->D distance covered
    uncovered_head_km: int          # intended origin .. this boarding point
    uncovered_tail_km: int          # this alighting point .. intended dest

    @property
    def confirmable(self) -> bool:
        return self.status.confirmable
