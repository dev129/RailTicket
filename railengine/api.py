"""HTTP surface over the two engines (deployable artifact).

    uvicorn railengine.api:app --host 0.0.0.0 --port 8000

Provider selection is automatic:
  * if RAIL_API_BASE and RAIL_API_KEY are set -> LiveApiProvider
    (schedules served from the bundled static/mock source, which is cacheable)
  * otherwise -> MockProvider (offline demo corridor)
"""

from __future__ import annotations

import os
from datetime import date as Date
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .journey import BrokenJourney, find_broken_journeys
from .journey_live import find_broken_journeys_live
from .models import SegmentOption, SegmentQuery, TravelClass
from .next_seat import find_next_available
from .providers.base import AvailabilityProvider
from .providers.irctcdev import IrctcDevProvider
from .providers.mock import STATIONS, MockProvider

STATIC_DIR = Path(__file__).parent / "static"


# --------------------------------------------------------------------------- #
# Provider wiring
#   default  -> live irctc.dev (real IR PRS data)
#   USE_MOCK -> offline demo corridor
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def get_provider() -> AvailabilityProvider:
    if os.environ.get("USE_MOCK"):
        return MockProvider()
    return IrctcDevProvider()


def provider_mode() -> str:
    return "mock" if isinstance(get_provider(), MockProvider) else "live (irctc.dev)"


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def _name(code: str) -> str:
    p = get_provider()
    namer = getattr(p, "station_name", None)
    if namer:
        n = namer(code)
        if n and n != code:
            return n
    return STATIONS[code].name if code in STATIONS else code


def _station(code: str) -> dict:
    return {"code": code, "name": _name(code)}


def _opt_json(o: SegmentOption) -> dict:
    return {
        "train_no": o.train_no,
        "class": o.travel_class.value,
        "from": _station(o.from_code),
        "to": _station(o.to_code),
        "status": {"state": o.status.state.value, "number": o.status.number,
                   "text": str(o.status), "raw": o.status.raw},
        "confirmable": o.confirmable,
        "coverage_pct": round(o.coverage * 100, 1),
        "uncovered_head_km": o.uncovered_head_km,
        "uncovered_tail_km": o.uncovered_tail_km,
    }


def _hhmm(abs_min: int) -> str:
    day, rem = divmod(abs_min, 1440)
    return f"{rem // 60:02d}:{rem % 60:02d}" + (f" +{day}d" if day else "")


def _journey_json(j: BrokenJourney) -> dict:
    return {
        "breaks": j.breaks,
        "total_wait_min": j.total_wait_min,
        "arrive": _hhmm(j.arrival_abs),
        "transfer": _station(j.legs[0].alight),
        "legs": [
            {
                "train_no": l.train.number,
                "train_name": l.train.name,
                "from": _station(l.board),
                "to": _station(l.alight),
                "dep": _hhmm(l.dep_abs),
                "arr": _hhmm(l.arr_abs),
                "class": l.travel_class.value,
                "status": str(l.status),
            }
            for l in j.legs
        ],
    }


def _parse_classes(raw: str) -> list[TravelClass]:
    out = []
    for token in raw.split(","):
        token = token.strip().upper()
        if not token:
            continue
        try:
            out.append(TravelClass(token))
        except ValueError:
            raise HTTPException(400, f"unknown class '{token}'")
    if not out:
        raise HTTPException(400, "no valid classes")
    return out


def _parse_date(raw: str) -> Date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
app = FastAPI(title="railengine", version="0.1.0",
              description="Next-available-seat + break-journey engine")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "provider": provider_mode()}


@app.get("/api/next-seat")
def next_seat(
    train: str = Query(..., description="train number, e.g. 19666"),
    date: str = Query(..., description="YYYY-MM-DD"),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    classes: str = Query("SL,3A,2A"),
    full: bool = Query(False, description="full scan vs budgeted probe"),
) -> dict:
    provider = get_provider()
    try:
        results = find_next_available(
            provider, train, _parse_date(date), from_.upper(), to.upper(),
            _parse_classes(classes), full_scan=full,
        )
    except KeyError as e:
        raise HTTPException(404, f"not found: {e}")

    out = {}
    for cls, options in results.items():
        baseline = next((o for o in options if o.from_seq == 0
                         and o.to_code == to.upper()), None)
        best = next((o for o in options if o.confirmable), None)
        out[cls.value] = {
            "baseline": _opt_json(baseline) if baseline else None,
            "best_confirmable": _opt_json(best) if best else None,
            "options": [_opt_json(o) for o in options],
        }
    return {"train": train, "from": _station(from_.upper()),
            "to": _station(to.upper()), "provider": provider_mode(), "classes": out}


@app.get("/api/break-journey")
def break_journey(
    date: str = Query(...),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    classes: str = Query("SL,3A,2A"),
    min_connection_min: int = Query(60, ge=0),
) -> dict:
    provider = get_provider()
    o, d = from_.upper(), to.upper()
    cls = _parse_classes(classes)
    tdate = _parse_date(date)

    if isinstance(provider, MockProvider):
        journeys = find_broken_journeys(provider, tdate, o, d, cls,
                                        min_connection_min=min_connection_min)
    else:
        journeys = find_broken_journeys_live(provider, tdate, o, d, cls,
                                             min_connection_min=min_connection_min)

    note = None
    if not journeys and not isinstance(provider, MockProvider):
        note = ("No confirmed two-train break found. Either every candidate leg was "
                "waitlisted on this date (common on saturated routes to big cities), or "
                "the free irctc.dev tier rate-limited this multi-call search — wait a "
                "minute and try again, pick a less-booked date, or add more classes.")
    return {"from": _station(o), "to": _station(d),
            "provider": provider_mode(), "note": note,
            "journeys": [_journey_json(j) for j in journeys]}


def _route_trains(provider, origin, dest, tdate, max_trains):
    """Normalized list of trains serving origin->dest, for live or mock."""
    searcher = getattr(provider, "search_trains", None)
    if searcher:
        rows = searcher(origin, dest, tdate)[:max_trains]
        return [{"number": r["number"], "name": r["name"],
                 "dep": r.get("dep"), "arr": r.get("arr")} for r in rows]
    out = []
    for t in provider.trains_serving(origin, dest)[:max_trains]:
        bs, as_ = t.stops[t.seq_of(origin)], t.stops[t.seq_of(dest)]
        out.append({"number": t.number, "name": t.name, "dep": bs.dep, "arr": as_.arr})
    return out


@app.get("/api/trip")
def trip(
    date: str = Query(..., description="YYYY-MM-DD"),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    classes: str = Query("3A,2A"),
    max_trains: int = Query(6, ge=1, le=12),
) -> dict:
    """Trains running from->to on a date, each with per-class availability.

    This is the passenger-facing entry point: no train number required.
    """
    provider = get_provider()
    o, d = from_.upper(), to.upper()
    tdate = _parse_date(date)
    cls = _parse_classes(classes)

    trains = _route_trains(provider, o, d, tdate, max_trains)
    out = []
    for t in trains:
        per_class = {}
        for c in cls:
            st = provider.get_availability(SegmentQuery(t["number"], tdate, o, d, c))
            per_class[c.value] = {"state": st.state.value, "number": st.number,
                                  "text": str(st), "confirmable": st.confirmable}
        out.append({"train_no": t["number"], "name": t["name"],
                    "dep": t.get("dep"), "arr": t.get("arr"), "classes": per_class})
    return {"from": _station(o), "to": _station(d), "date": date,
            "provider": provider_mode(), "trains": out}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
