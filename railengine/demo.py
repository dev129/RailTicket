"""Runnable demo of both features on the Jaipur -> Asarva corridor.

    python -m railengine.demo

Uses MockProvider (offline, no API key). The engine code is identical for
LiveApiProvider; only the provider construction changes.
"""

from __future__ import annotations

from datetime import date

from .journey import find_broken_journeys
from .models import StatusState, TravelClass
from .next_seat import find_next_available
from .providers.mock import STATIONS, MockProvider

HR = "-" * 68


def _name(code: str) -> str:
    return STATIONS[code].name if code in STATIONS else code


def _hhmm(abs_min: int) -> str:
    day, rem = divmod(abs_min, 1440)
    return f"{rem // 60:02d}:{rem % 60:02d}" + (f" +{day}d" if day else "")


def demo() -> None:
    provider = MockProvider()
    travel_date = date(2026, 11, 20)
    O, D = "JP", "ASV"
    chosen = [TravelClass.SL, TravelClass.A3, TravelClass.A2]

    print(HR)
    print(f"Trip: {_name(O)} -> {_name(D)}  on 2026-11-20   train 19666")
    print(f"Classes requested: {', '.join(c.label for c in chosen)}")
    print(HR)

    # ---- Feature 2: next available seat (full scan for transparency) ------- #
    print("\n[ FEATURE 2 ]  Next available seat (same train, shift boarding)\n")
    results = find_next_available(
        provider, "19666", travel_date, O, D, chosen, full_scan=True
    )
    for cls, options in results.items():
        print(f"  Class {cls.value} ({cls.label}):")
        if not options:
            print("    not offered on this train\n")
            continue
        baseline = next(o for o in options if o.from_seq == 0 and o.to_code == D)
        print(f"    intended {_name(O)}->{_name(D)}:  {baseline.status}  "
              f"({'CONFIRMABLE' if baseline.confirmable else 'waitlisted'})")
        best = next((o for o in options if o.confirmable), None)
        for o in options:
            if o is baseline:
                continue
            tag = " <-- best" if o is best else ""
            cov = f"{o.coverage*100:4.0f}% covered"
            miss = []
            if o.uncovered_head_km:
                miss.append(f"{_name(O)}->{_name(o.from_code)} ({o.uncovered_head_km}km)")
            if o.uncovered_tail_km:
                miss.append(f"{_name(o.to_code)}->{_name(D)} ({o.uncovered_tail_km}km)")
            miss_s = ("  miss: " + ", ".join(miss)) if miss else ""
            mark = "OK " if o.confirmable else "   "
            print(f"    {mark}{_name(o.from_code)}->{_name(o.to_code)}: "
                  f"{str(o.status):<9} {cov}{miss_s}{tag}")
        if best and best.uncovered_head_km:
            print(f"    -> head leg {_name(O)}->{_name(best.from_code)} is uncovered; "
                  f"Feature 1 can fill it.")
        print()

    # ---- budgeted probe: same answer, fewer API calls --------------------- #
    p2 = MockProvider()
    find_next_available(p2, "19666", travel_date, O, D, [TravelClass.SL], full_scan=False)
    pfull = MockProvider()
    find_next_available(pfull, "19666", travel_date, O, D, [TravelClass.SL], full_scan=True)
    print(f"  [API budget, SL]  full scan = {pfull.call_count} calls   "
          f"budgeted probe = {p2.call_count} calls")

    # ---- Feature 1: break my journey -------------------------------------- #
    print("\n" + HR)
    print("\n[ FEATURE 1 ]  Break my journey (multi-train, >=60 min connection)\n")
    journeys = find_broken_journeys(provider, travel_date, O, D, chosen)
    if not journeys:
        print("  no confirmable broken itinerary found")
    for j in journeys[:3]:
        legs = " + ".join(f"{l.train.number}" for l in j.legs)
        print(f"  Option: {legs}   breaks={j.breaks}  "
              f"total wait={j.total_wait_min} min  arrive {_hhmm(j.arrival_abs)}")
        for l in j.legs:
            print(f"    {l.train.number} {l.train.name:<22} "
                  f"{_name(l.board)} {_hhmm(l.dep_abs)} -> {_name(l.alight)} "
                  f"{_hhmm(l.arr_abs)}   {l.travel_class.value} {l.status}")
        x = j.legs[0].alight
        print(f"    break at {_name(x)}: wait {j.total_wait_min} min "
              f"({_hhmm(j.legs[0].arr_abs)} -> {_hhmm(j.legs[1].dep_abs)})\n")

    print(HR)


if __name__ == "__main__":
    demo()
