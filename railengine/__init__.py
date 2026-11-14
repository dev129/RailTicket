"""railengine - a rail-journey planning core.

Public surface:
    find_next_available   (Feature 2: next available seat)
    find_broken_journeys  (Feature 1: break my journey)
    MockProvider / LiveApiProvider
"""

from .journey import BrokenJourney, Leg, find_broken_journeys
from .models import (
    AvailabilityStatus,
    SegmentOption,
    StatusState,
    Station,
    Train,
    TravelClass,
)
from .next_seat import find_next_available
from .providers.live import LiveApiProvider
from .providers.mock import MockProvider

__all__ = [
    "find_next_available",
    "find_broken_journeys",
    "BrokenJourney",
    "Leg",
    "MockProvider",
    "LiveApiProvider",
    "AvailabilityStatus",
    "SegmentOption",
    "StatusState",
    "Station",
    "Train",
    "TravelClass",
]
