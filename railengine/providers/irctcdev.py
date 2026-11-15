"""Live provider backed by irctc.dev (real IR PRS data).

Endpoints used:
  GET /api/v1/trains/{trainNo}               -> route (data.stations[])
  GET /api/v1/trains/{trainNo}/availability  -> 14-day availability[] per date
      params: from, to, date (YYYY-MM-DD), class (SL/3E/3A/2A/1A), quota (GN...)

Auth: Authorization: Bearer <key>.
  * In this cloud session the network proxy injects the saved key, so a
    placeholder token is fine (the proxy overwrites the header).
  * In a real deployment, set IRCTC_DEV_KEY and it is sent as-is.

Train discovery for break-journey (which trains run O->D) is delegated to a
`discovery` provider when supplied (e.g. the RapidAPI schedule source), since
irctc.dev is queried per train number.
"""

from __future__ import annotations

import os
from functools import lru_cache

from ..availability import parse_status
from ..models import (
    AvailabilityStatus,
    SegmentQuery,
    StatusState,
    Train,
    TrainStop,
    TravelClass,
)
from .base import AvailabilityProvider

_ALL_CLASSES = (
    TravelClass.SL, TravelClass.E3, TravelClass.A3, TravelClass.A2, TravelClass.A1,
)


class IrctcDevProvider(AvailabilityProvider):
    BASE = "https://api.irctc.dev"

    def __init__(self, quota: str = "GN", timeout: float = 45.0,
                 discovery: AvailabilityProvider | None = None) -> None:
        self.quota = quota
        self.timeout = timeout
        self._discovery = discovery
        self._train_cache: dict[str, Train] = {}
        self._names: dict[str, str] = {}
        self._calls = 0

    def station_name(self, code: str) -> str:
        return self._names.get(code, code)

    # --- auth -------------------------------------------------------------- #
    def _headers(self) -> dict:
        # Proxy overwrites this in-session; real value via env in deployment.
        return {"Authorization": f"Bearer {os.environ.get('IRCTC_DEV_KEY', 'proxy-injected')}"}

    def _get(self, url: str, params: dict | None = None):
        import requests  # lazy: stdlib-only paths need nothing
        return requests.get(url, headers=self._headers(), params=params, timeout=self.timeout)

    # --- static ------------------------------------------------------------ #
    def get_train(self, train_no: str) -> Train:
        train_no = str(train_no)
        if train_no in self._train_cache:
            return self._train_cache[train_no]

        resp = self._get(f"{self.BASE}/api/v1/trains/{train_no}")
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success") or "data" not in body:
            raise KeyError(f"train {train_no} not found on irctc.dev")

        data = body["data"]
        for s in data["stations"]:
            if s.get("name"):
                self._names[s["code"]] = s["name"].title()
        stops = tuple(
            TrainStop(
                station=s["code"],
                seq=int(s["seq"]) - 1,                 # irctc.dev is 1-based
                arr=s.get("arrival"),
                dep=s.get("departure"),
                day_offset=int(s.get("dayOffset") or 0),
                dist_km=int(s.get("distanceKm") or 0),
            )
            for s in data["stations"]
        )
        train = Train(
            number=str(data.get("trainNo", train_no)),
            name=data.get("trainName", ""),
            stops=stops,
            classes=_ALL_CLASSES,          # availability call reports if a class is absent
        )
        self._train_cache[train_no] = train
        return train

    def trains_serving(self, origin: str, dest: str) -> list[Train]:
        if self._discovery is None:
            raise NotImplementedError(
                "Break-journey needs a train-discovery source; pass `discovery=` "
                "(e.g. the RapidAPI schedule provider)."
            )
        numbers = [t.number for t in self._discovery.trains_serving(origin, dest)]
        out = []
        for n in numbers:
            try:
                out.append(self.get_train(n))
            except Exception:
                continue
        return out

    # --- dynamic ----------------------------------------------------------- #
    def get_availability(self, query: SegmentQuery) -> AvailabilityStatus:
        self._calls += 1
        want = query.travel_date.isoformat()
        resp = self._get(
            f"{self.BASE}/api/v1/trains/{query.train_no}/availability",
            params={
                "from": query.from_code,
                "to": query.to_code,
                "date": want,
                "class": query.travel_class.value,
                "quota": self.quota,
            },
        )
        if resp.status_code != 200:
            return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, f"HTTP {resp.status_code}")
        body = resp.json()
        if not body.get("success"):
            return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, str(body.get("error", "")))
        arr = body.get("availability") or []
        entry = next((a for a in arr if a.get("date") == want), arr[0] if arr else None)
        if not entry:
            return AvailabilityStatus(StatusState.NOT_AVAILABLE, 0, "no availability row")
        return parse_status(entry.get("status", ""))

    @property
    def call_count(self) -> int:
        return self._calls
