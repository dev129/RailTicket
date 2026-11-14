"""Feature 1 - 'Break my journey'.

Find a sequence of train legs O -> ... -> D where consecutive legs connect at
a shared station with a transfer gap >= MCT (default 60 min), each leg is
seat-feasible in a chosen class, minimizing (number of breaks, then total
connection wait).

This prototype implements the **single-break** case (2 legs), which covers
the Jaipur->Udaipur->Asarva scenario. The generalization to k breaks is
RAPTOR / Connection-Scan (round k = journeys with k transfers, Pareto on
arrival-time vs. transfers); the interfaces here are shaped so that drop-in
is mechanical -- see README 'Roadmap'.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from typing import Iterable

from .models import AvailabilityStatus, SegmentQuery, Train, TravelClass
from .providers.base import AvailabilityProvider

MIN_CONNECTION_MIN = 60     # the user's "at least an hour"


def _abs_min(day_offset: int, hhmm: str | None) -> int | None:
    if hhmm is None:
        return None
    h, m = hhmm.split(":")
    return day_offset * 1440 + int(h) * 60 + int(m)


@dataclass
class Leg:
    train: Train
    board: str
    alight: str
    dep_abs: int           # absolute minutes from journey start
    arr_abs: int
    travel_class: TravelClass
    status: AvailabilityStatus


@dataclass
class BrokenJourney:
    legs: list[Leg]

    @property
    def breaks(self) -> int:
        return len(self.legs) - 1

    @property
    def total_wait_min(self) -> int:
        return sum(self.legs[i + 1].dep_abs - self.legs[i].arr_abs
                   for i in range(len(self.legs) - 1))

    @property
    def arrival_abs(self) -> int:
        return self.legs[-1].arr_abs


def _leg_feasible(provider, train, board, alight, travel_date, cls) -> AvailabilityStatus | None:
    """Return status if the leg is confirmable in `cls`, else None."""
    status = provider.get_availability(
        SegmentQuery(train.number, travel_date, board, alight, cls)
    )
    return status if status.confirmable else None


def find_broken_journeys(
    provider: AvailabilityProvider,
    travel_date: Date,
    origin: str,
    dest: str,
    classes: Iterable[TravelClass],
    *,
    min_connection_min: int = MIN_CONNECTION_MIN,
    max_connection_min: int = 12 * 60,
) -> list[BrokenJourney]:
    """Single-break itineraries O->X->D, each leg confirmable, ranked.

    Ranking: fewest breaks, then shortest total wait, then earliest arrival.
    """
    classes = list(classes)
    results: list[BrokenJourney] = []

    # Candidate transfer stations = stations served after O by some train,
    # and before D by some (possibly other) train.
    t_from_o = _trains_from(provider, origin)
    t_to_d = _trains_to(provider, dest)

    transfer_stations = {
        s for t in t_from_o for s in _stations_after(t, origin)
    } & {
        s for t in t_to_d for s in _stations_before(t, dest)
    }

    for x in transfer_stations:
        for t1 in t_from_o:
            if not t1.serves(origin, x):
                continue
            for t2 in t_to_d:
                if not t2.serves(x, dest) or t2.number == t1.number:
                    continue
                arr = _abs_min(t1.stop_at_seq(t1.seq_of(x)).day_offset,
                               t1.stop_at_seq(t1.seq_of(x)).arr)
                dep = _abs_min(t2.stop_at_seq(t2.seq_of(x)).day_offset,
                               t2.stop_at_seq(t2.seq_of(x)).dep)
                if arr is None or dep is None:
                    continue
                gap = dep - arr
                if not (min_connection_min <= gap <= max_connection_min):
                    continue
                for cls in classes:
                    s1 = _leg_feasible(provider, t1, origin, x, travel_date, cls)
                    s2 = _leg_feasible(provider, t2, x, dest, travel_date, cls)
                    if s1 is None or s2 is None:
                        continue
                    leg1 = Leg(t1, origin, x,
                               _abs_min(t1.stops[t1.seq_of(origin)].day_offset,
                                        t1.stops[t1.seq_of(origin)].dep),
                               arr, cls, s1)
                    leg2 = Leg(t2, x, dest, dep,
                               _abs_min(t2.stops[t2.seq_of(dest)].day_offset,
                                        t2.stops[t2.seq_of(dest)].arr),
                               cls, s2)
                    results.append(BrokenJourney([leg1, leg2]))

    results.sort(key=lambda j: (j.breaks, j.total_wait_min, j.arrival_abs))
    return results


# --------------------------------------------------------------------------- #
# small schedule helpers
# --------------------------------------------------------------------------- #
def _trains_from(provider: AvailabilityProvider, origin: str) -> list[Train]:
    return [t for t in _all_trains(provider) if origin in {s.station for s in t.stops}
            and t.seq_of(origin) < len(t.stops) - 1]


def _trains_to(provider: AvailabilityProvider, dest: str) -> list[Train]:
    return [t for t in _all_trains(provider) if dest in {s.station for s in t.stops}
            and t.seq_of(dest) > 0]


def _all_trains(provider: AvailabilityProvider) -> list[Train]:
    # MockProvider exposes its table; live mode supplies a schedule source.
    inner = getattr(provider, "_trains", None)
    if inner is not None:
        return list(inner.values())
    sched = getattr(provider, "_schedules", None)
    if sched is not None:
        return _all_trains(sched)
    return []


def _stations_after(train: Train, station: str) -> set[str]:
    i = train.seq_of(station)
    return {s.station for s in train.stops if s.seq > i}


def _stations_before(train: Train, station: str) -> set[str]:
    i = train.seq_of(station)
    return {s.station for s in train.stops if s.seq < i}
