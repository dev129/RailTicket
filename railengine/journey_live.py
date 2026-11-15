"""Live 'break my journey' over irctc.dev.

Single break, O -> X -> D:
  1. Candidate transfer stations X = intermediate stops of a direct O->D train.
  2. For each X, discover trains O->X and X->D (search endpoint, with timing).
  3. Check real availability on each distinct leg (cached) for each class.
  4. For each (X, class), pair a confirmed O->X train with a confirmed X->D
     train whose connection gap is in [min, max], minimizing the gap.

Availability is per leg, so legs are checked once each and combined — all
calls run concurrently and the candidate set is capped to keep one search fast.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date as Date
from typing import Iterable

from .journey import BrokenJourney, Leg
from .models import SegmentQuery, Train, TravelClass

MIN_CONNECTION_MIN = 60
_MAX_X = 3            # transfer stations sampled across the route
_N1 = 2              # O->X trains considered per station (soonest arrivals)
_N2 = 3              # X->D trains considered per station (soonest departures)
_MAX_RESULTS = 6
_WORKERS = 3         # keep well under the irctc.dev free-tier rate limit
_BIG = 10 ** 9


def _abs(day: int, hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = hhmm.split(":")
    return day * 1440 + int(h) * 60 + int(m)


def find_broken_journeys_live(
    provider,
    travel_date: Date,
    origin: str,
    dest: str,
    classes: Iterable[TravelClass],
    *,
    min_connection_min: int = MIN_CONNECTION_MIN,
    max_connection_min: int = 12 * 60,
) -> list[BrokenJourney]:
    classes = list(classes)

    # 1) candidate transfer stations from a direct train's route
    direct = provider.search_trains(origin, dest, travel_date)
    if not direct:
        return []
    try:
        route: Train = provider.get_train(direct[0]["number"])
        o, d = route.seq_of(origin), route.seq_of(dest)
    except Exception:
        return []
    inter = [route.stop_at_seq(i).station for i in range(o + 1, d)]
    if not inter:
        return []
    if len(inter) > _MAX_X:
        step = len(inter) / _MAX_X
        inter = [inter[int(i * step)] for i in range(_MAX_X)]

    # 2) discover leg trains per X (parallel), keep the soonest few
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        f1 = {x: ex.submit(provider.search_trains, origin, x, travel_date) for x in inter}
        f2 = {x: ex.submit(provider.search_trains, x, dest, travel_date) for x in inter}
        leg1 = {x: sorted(f1[x].result(), key=lambda t: _abs(t["arr_day"], t["arr"]) or _BIG)[:_N1]
                for x in inter}
        leg2 = {x: sorted(f2[x].result(), key=lambda t: _abs(t["dep_day"], t["dep"]) or _BIG)[:_N2]
                for x in inter}

    # 3) check availability of every distinct leg (cached), concurrently
    jobs = set()
    for x in inter:
        for cls in classes:
            for t1 in leg1[x]:
                jobs.add((t1["number"], origin, x, cls.value))
            for t2 in leg2[x]:
                jobs.add((t2["number"], x, dest, cls.value))

    def fetch(job):
        tn, frm, to, cval = job
        st = provider.get_availability(SegmentQuery(tn, travel_date, frm, to, TravelClass(cval)))
        return job, st

    status: dict[tuple, object] = {}
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for job, st in ex.map(fetch, list(jobs)):
            status[job] = st

    # 4) for each (X, class), best confirmed pair by connection gap
    out: list[BrokenJourney] = []
    for x in inter:
        for cls in classes:
            conf1 = [t for t in leg1[x] if status[(t["number"], origin, x, cls.value)].confirmable]
            conf2 = [t for t in leg2[x] if status[(t["number"], x, dest, cls.value)].confirmable]
            best = None
            for t1 in conf1:
                arr_x = _abs(t1["arr_day"], t1["arr"])
                dep_o = _abs(t1["dep_day"], t1["dep"])
                for t2 in conf2:
                    dep_x = _abs(t2["dep_day"], t2["dep"])
                    arr_d = _abs(t2["arr_day"], t2["arr"])
                    gap = dep_x - arr_x
                    if min_connection_min <= gap <= max_connection_min:
                        if best is None or gap < best[-1]:
                            best = (t1, t2, dep_o, arr_x, dep_x, arr_d, gap)
            if best:
                t1, t2, dep_o, arr_x, dep_x, arr_d, gap = best
                la = Leg(Train(t1["number"], t1["name"], (), ()), origin, x, dep_o, arr_x,
                         cls, status[(t1["number"], origin, x, cls.value)])
                lb = Leg(Train(t2["number"], t2["name"], (), ()), x, dest, dep_x, arr_d,
                         cls, status[(t2["number"], x, dest, cls.value)])
                out.append(BrokenJourney([la, lb]))

    out.sort(key=lambda j: (j.total_wait_min, j.arrival_abs))
    return out[:_MAX_RESULTS]
