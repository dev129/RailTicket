"""Adapter for a real IRCTC-style availability API.

This is intentionally a thin, swappable adapter. Production availability
sources (RapidAPI "IRCTC" providers, railwayapi-style services, or an
internal gateway) differ only in host, auth header, and JSON shape -- all of
which are isolated here. The engines above never change.

Configuration (env vars):
    RAIL_API_BASE   e.g. https://irctc1.p.rapidapi.com
    RAIL_API_KEY    your key
    RAIL_API_HOST   RapidAPI host header (optional)

Static schedule data is treated as *cacheable* (it changes rarely); only
availability is fetched live. For the prototype, schedules are delegated to
a bundled static source if the live schedule endpoint is not configured.
"""

from __future__ import annotations

import json
import os
from datetime import date as Date
from functools import lru_cache

from ..availability import parse_status
from ..models import AvailabilityStatus, SegmentQuery, StatusState, Train
from .base import AvailabilityProvider


class LiveApiProvider(AvailabilityProvider):
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_host: str | None = None,
        schedule_source: AvailabilityProvider | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("RAIL_API_BASE", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("RAIL_API_KEY", "")
        self.api_host = api_host or os.environ.get("RAIL_API_HOST", "")
        self.timeout = timeout
        # Schedules change rarely -> allow a static/mock source to supply them.
        self._schedules = schedule_source
        self._calls = 0

    # --- static ------------------------------------------------------------ #
    def get_train(self, train_no: str) -> Train:
        if self._schedules is not None:
            return self._schedules.get_train(train_no)
        raise NotImplementedError("Configure a schedule source for live mode.")

    def trains_serving(self, origin: str, dest: str) -> list[Train]:
        if self._schedules is not None:
            return self._schedules.trains_serving(origin, dest)
        raise NotImplementedError("Configure a schedule source for live mode.")

    # --- dynamic ----------------------------------------------------------- #
    def get_availability(self, query: SegmentQuery) -> AvailabilityStatus:
        self._calls += 1
        return self._fetch(
            query.train_no,
            query.from_code,
            query.to_code,
            query.travel_class.value,
            query.travel_date.isoformat(),
        )

    @lru_cache(maxsize=4096)
    def _fetch(self, train_no: str, frm: str, to: str, cls: str, day: str) -> AvailabilityStatus:
        if not (self.base_url and self.api_key):
            raise RuntimeError(
                "LiveApiProvider not configured. Set RAIL_API_BASE and "
                "RAIL_API_KEY, or use MockProvider for offline runs."
            )
        import requests  # imported lazily so stdlib-only mock path needs nothing

        url = f"{self.base_url}/api/v3/checkSeatAvailability"
        headers = {"X-RapidAPI-Key": self.api_key}
        if self.api_host:
            headers["X-RapidAPI-Host"] = self.api_host
        params = {
            "trainNo": train_no,
            "fromStationCode": frm,
            "toStationCode": to,
            "classType": cls,
            "quota": "GN",
            "date": day,
        }
        # NOTE: HTTPS_PROXY / CA bundle are honored automatically by requests
        # via the environment; do not disable TLS verification.
        resp = requests.get(url, headers=headers, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return self._map_response(resp.json())

    @staticmethod
    def _map_response(payload: dict) -> AvailabilityStatus:
        """Map a provider JSON body to a normalized status.

        Shapes vary; we look for the common ``data[0].current_status`` and
        fall back to scanning for any status-looking string.
        """
        try:
            data = payload.get("data")
            if isinstance(data, list) and data:
                raw = data[0].get("current_status") or data[0].get("confirm_status") or ""
                return parse_status(str(raw))
        except (AttributeError, KeyError, TypeError):
            pass
        return parse_status(json.dumps(payload))

    @property
    def call_count(self) -> int:
        return self._calls
