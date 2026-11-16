"""Live 'break my journey' over irctc.dev.

Single break, O -> X -> D:
  1. Candidate transfer stations X = intermediate stops of a direct O->D train.
  2. For each X, discover trains O->X and X->D (search endpoint, with timing).
  3. Phase A: check O->X availability (first leg) for each class.
  4. Phase B: only where some O->X is confirmable, check X->D availability.
  5. Pair a confirmed O->X with a confirmed X->D, minimizing the connection gap.

All availability runs concurrently under a hard time budget, so one search
returns quickly even when the free-tier API rate-limits. Results are cached on
the provider, so repeat searches are near-instant.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FTimeout
from datetime import date as Date
from typing import Iterable

from .journey import BrokenJourney, Leg
from .models import SegmentQuery, Train, TravelClass

MIN_CONNECTION_MIN = 60
_MAX_X = 3
_N1 = 2
_N2 = 3
_MAX_RESULTS = 6
_WORKERS = 4
_TIME_BUDGET_S = 11.0
_DISCOVERY_BUDGET_S = 5.0
_BIG = 10 ** 9


def _abs(day: int, hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = hhmm.split(":")
    return day * 1440 + int(h) * 60 + int(m)


def _run(jobs: list[tuple], workers: int, deadline: float) -> dict:
    """jobs = [(key, thunk)]. Collect results until done or `deadline`.

    Non-blocking on timeout: stragglers are abandoned (shutdown without wait)
    so the caller returns within the budget even if the API is slow.
    """
    results: dict = {}
    remaining = deadline - time.time()
    if remaining <= 0 or not jobs:
        return results
    ex = ThreadPoolExecutor(max_workers=workers)
    futs = {ex.submit(fn): key for key, fn in jobs}
    try:
        for fut in as_completed(futs, timeout=max(0.05, remaining)):
            results[futs[fut]] = fut.result()
    except FTimeout:
        pass
    ex.shutdown(wait=False, cancel_futures=True)
    return results


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
    deadline = time.time() + _TIME_BUDGET_S

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

    # 2) discover leg trains per X (parallel, time-bounded), keep soonest few
    disc_deadline = time.time() + _DISCOVERY_BUDGET_S
    ex = ThreadPoolExecutor(max_workers=_WORKERS)
    f1 = {x: ex.submit(provider.search_trains, origin, x, travel_date) for x in inter}
    f2 = {x: ex.submit(provider.search_trains, x, dest, travel_date) for x in inter}

    def _res(fut):
        try:
            return fut.result(timeout=max(0.05, disc_deadline - time.time()))
        except Exception:
            return []

    leg1 = {x: sorted(_res(f1[x]), key=lambda t: _abs(t["arr_day"], t["arr"]) or _BIG)[:_N1]
            for x in inter}
    leg2 = {x: sorted(_res(f2[x]), key=lambda t: _abs(t["dep_day"], t["dep"]) or _BIG)[:_N2]
            for x in inter}
    ex.shutdown(wait=False, cancel_futures=True)

    def av(train_no, frm, to, cls):
        return lambda: provider.get_availability(SegmentQuery(train_no, travel_date, frm, to, cls))

    # 3) Phase A — first leg O->X
    jobsA = [((x, t["number"], c.value), av(t["number"], origin, x, c))
             for x in inter for c in classes for t in leg1[x]]
    stA = _run(jobsA, _WORKERS, deadline)

    # 4) Phase B — second leg X->D, only where first leg can confirm
    jobsB = []
    for x in inter:
        for c in classes:
            if any(stA.get((x, t["number"], c.value), _NC).confirmable for t in leg1[x]):
                for t in leg2[x]:
                    jobsB.append(((x, t["number"], c.value), av(t["number"], x, dest, c)))
    stB = _run(jobsB, _WORKERS, deadline)

    # 5) best confirmed pair per (X, class), by connection gap
    out: list[BrokenJourney] = []
    for x in inter:
        for c in classes:
            conf1 = [t for t in leg1[x] if stA.get((x, t["number"], c.value), _NC).confirmable]
            conf2 = [t for t in leg2[x] if stB.get((x, t["number"], c.value), _NC).confirmable]
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
                         c, stA[(x, t1["number"], c.value)])
                lb = Leg(Train(t2["number"], t2["name"], (), ()), x, dest, dep_x, arr_d,
                         c, stB[(x, t2["number"], c.value)])
                out.append(BrokenJourney([la, lb]))

    out.sort(key=lambda j: (j.total_wait_min, j.arrival_abs))
    return out[:_MAX_RESULTS]


class _NotConfirmable:
    confirmable = False


_NC = _NotConfirmable()
