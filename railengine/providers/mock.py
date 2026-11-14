"""Offline provider that reproduces the real problem faithfully.

Key idea: the *ground truth* here is a per-edge occupancy profile
(``edge_load[train][class]`` = berths occupied on each inter-stop edge).
Segment availability is then derived exactly as the physics dictates:

    available(b, a) = capacity - max(edge_load over edges in [b, a))

...but the engines never see ``edge_load``. They only receive the resulting
IRCTC-style *string* (``WL 134`` / ``AVL 3``), exactly as a live API would
hand it over. So the mock exercises the full normalize->scan pipeline while
staying internally consistent with the Jaipur->Asarva narrative.
"""

from __future__ import annotations

from datetime import date as Date

from ..models import (
    AvailabilityStatus,
    SegmentQuery,
    StatusState,
    Station,
    Train,
    TrainStop,
    TravelClass,
)
from .base import AvailabilityProvider

# --------------------------------------------------------------------------- #
# Corridor: Jaipur -> Ajmer -> Udaipur City -> Himmatnagar -> Asarva
# --------------------------------------------------------------------------- #
STATIONS = {
    "JP": Station("JP", "Jaipur Jn"),
    "AII": Station("AII", "Ajmer Jn"),
    "UDZ": Station("UDZ", "Udaipur City"),
    "HMT": Station("HMT", "Himmatnagar"),
    "ASV": Station("ASV", "Asarva Jn"),
}


def _train_direct() -> Train:
    """19666-style through train, but Jaipur->Asarva is heavily waitlisted."""
    stops = (
        TrainStop("JP", 0, None, "14:05", 0, 0),
        TrainStop("AII", 1, "16:10", "16:20", 0, 135),
        TrainStop("UDZ", 2, "21:30", "21:45", 0, 435),
        TrainStop("HMT", 3, "00:40", "00:45", 1, 615),
        TrainStop("ASV", 4, "03:30", None, 1, 730),
    )
    return Train("19666", "Jaipur - Asarva Exp",
                 stops, (TravelClass.SL, TravelClass.E3, TravelClass.A3, TravelClass.A2))


def _train_leg1() -> Train:
    """Feeder into Udaipur, arriving ~21:30 (for break-journey demo)."""
    stops = (
        TrainStop("JP", 0, None, "13:20", 0, 0),
        TrainStop("AII", 1, "15:25", "15:30", 0, 135),
        TrainStop("UDZ", 2, "21:25", None, 0, 435),
    )
    return Train("20473", "Jaipur - Udaipur SF",
                 stops, (TravelClass.SL, TravelClass.A3, TravelClass.A2))


def _train_leg2() -> Train:
    """Udaipur -> Asarva departing 22:50 (connection gap ~85 min, valid)."""
    stops = (
        TrainStop("UDZ", 0, None, "22:50", 0, 0),
        TrainStop("HMT", 1, "01:35", "01:40", 1, 180),
        TrainStop("ASV", 2, "04:20", None, 1, 295),
    )
    return Train("19704", "Udaipur - Asarva Exp",
                 stops, (TravelClass.SL, TravelClass.A3))


# capacity[class]
_CAPACITY = {
    TravelClass.SL: 72,
    TravelClass.E3: 78,
    TravelClass.A3: 64,
    TravelClass.A2: 46,
    TravelClass.A1: 18,
}

# Per-edge occupancy. Index i = edge between stop i and stop i+1.
# Story for 19666 SL: JP..AII..UDZ segments oversold (-> WL on long span),
# UDZ..HMT..ASV light (-> confirmable if you board at Udaipur).
_EDGE_LOAD: dict[str, dict[TravelClass, list[int]]] = {
    "19666": {
        # edges:        JP-AII  AII-UDZ  UDZ-HMT  HMT-ASV
        # Descending toward the tail -> boarding later clears the waitlist,
        # matching the user's WL134 -> WL78 -> AVBL ladder.
        TravelClass.SL: [206, 150, 69, 61],      # cap 72: JP->ASV WL134, AII WL78, UDZ AVBL3
        TravelClass.E3: [150, 120, 70, 66],
        TravelClass.A3: [74, 68, 40, 36],        # cap 64: JP->ASV WL10, AII WL4, UDZ AVBL24
        TravelClass.A2: [47, 45, 30, 28],        # cap 46: JP->ASV WL1, AII AVBL1, UDZ AVBL16
    },
    "20473": {
        # edges:        JP-AII  AII-UDZ
        TravelClass.SL: [40, 55],                # JP->UDZ comfortably available
        TravelClass.A3: [30, 41],
        TravelClass.A2: [20, 28],
    },
    "19704": {
        # edges:        UDZ-HMT  HMT-ASV
        TravelClass.SL: [48, 44],                # UDZ->ASV available
        TravelClass.A3: [40, 36],
    },
}


class MockProvider(AvailabilityProvider):
    def __init__(self) -> None:
        self._trains = {t.number: t for t in (_train_direct(), _train_leg1(), _train_leg2())}
        self._calls = 0

    # --- static ------------------------------------------------------------ #
    def get_train(self, train_no: str) -> Train:
        return self._trains[train_no]

    def trains_serving(self, origin: str, dest: str) -> list[Train]:
        return [t for t in self._trains.values() if t.serves(origin, dest)]

    # --- dynamic ----------------------------------------------------------- #
    def get_availability(self, query: SegmentQuery) -> AvailabilityStatus:
        self._calls += 1
        train = self._trains[query.train_no]

        if query.travel_class not in train.classes:
            return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, "NOT AVAILABLE")

        b = train.seq_of(query.from_code)
        a = train.seq_of(query.to_code)
        if b >= a:
            return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, "NOT AVAILABLE")

        cap = _CAPACITY[query.travel_class]
        loads = _EDGE_LOAD[query.train_no][query.travel_class]
        peak = max(loads[b:a])               # tightest edge dictates the span
        free = cap - peak

        raw = self._raw_string(free)
        from ..availability import parse_status
        return parse_status(raw)

    @staticmethod
    def _raw_string(free: int) -> str:
        if free >= 1:
            return f"AVAILABLE-{free:04d}"
        if free == 0:
            return "RAC 5"
        return f"GNWL {-free}/WL {-free}"

    @property
    def call_count(self) -> int:
        return self._calls
