"""Provider abstraction: the single seam between engines and data sources.

Engines depend ONLY on this interface. Concrete providers:
  * MockProvider  - internally consistent synthetic corridor, runs offline.
  * LiveApiProvider - adapter for a real IRCTC-style HTTP API (needs a key).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import AvailabilityStatus, SegmentQuery, Train


class AvailabilityProvider(ABC):
    """Supplies static schedules and dynamic availability."""

    # --- static ------------------------------------------------------------ #
    @abstractmethod
    def get_train(self, train_no: str) -> Train:
        """Return the full schedule (stops, classes) for a train."""

    @abstractmethod
    def trains_serving(self, origin: str, dest: str) -> list[Train]:
        """All trains whose route visits `origin` before `dest`."""

    # --- dynamic ----------------------------------------------------------- #
    @abstractmethod
    def get_availability(self, query: SegmentQuery) -> AvailabilityStatus:
        """One normalized availability lookup. May hit the network.

        Implementations SHOULD cache: the engines assume repeated identical
        queries are cheap.
        """

    # Observability hook (overridden by providers that count calls).
    @property
    def call_count(self) -> int:
        return 0
