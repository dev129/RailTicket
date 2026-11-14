from datetime import date

from railengine.journey import find_broken_journeys
from railengine.next_seat import find_next_available
from railengine.providers.mock import MockProvider
from railengine.models import TravelClass

DATE = date(2026, 11, 20)


def test_through_journey_is_waitlisted_but_subsegment_confirmable():
    p = MockProvider()
    res = find_next_available(p, "19666", DATE, "JP", "ASV", [TravelClass.SL], full_scan=True)
    sl = res[TravelClass.SL]
    baseline = next(o for o in sl if o.from_seq == 0 and o.to_code == "ASV")
    assert not baseline.confirmable                       # JP->ASV is WL
    best = next(o for o in sl if o.confirmable)
    assert best.to_code == "ASV" and best.from_code == "UDZ"   # board at Udaipur
    assert best.uncovered_head_km == 435                 # JP..UDZ left uncovered


def test_budgeted_probe_matches_full_scan_answer_with_fewer_calls():
    full = MockProvider()
    r_full = find_next_available(full, "19666", DATE, "JP", "ASV", [TravelClass.SL], full_scan=True)
    budget = MockProvider()
    r_bud = find_next_available(budget, "19666", DATE, "JP", "ASV", [TravelClass.SL], full_scan=False)

    def best_conf(res):
        return next(o for o in res[TravelClass.SL] if o.confirmable)

    assert best_conf(r_full).from_code == best_conf(r_bud).from_code
    assert budget.call_count < full.call_count            # the whole point


def test_class_filter_excludes_unoffered_class():
    p = MockProvider()
    res = find_next_available(p, "19704", DATE, "UDZ", "ASV", [TravelClass.A2], full_scan=True)
    assert res[TravelClass.A2] == []                      # 19704 has no 2A


def test_break_journey_respects_min_connection_and_is_confirmable():
    p = MockProvider()
    journeys = find_broken_journeys(p, DATE, "JP", "ASV", [TravelClass.SL])
    assert journeys, "expected at least one broken itinerary"
    j = journeys[0]
    assert j.breaks == 1
    assert j.total_wait_min >= 60                         # the user's >= 1 hour
    assert all(l.status.confirmable for l in j.legs)
    assert j.legs[0].alight == "UDZ"                      # break at Udaipur


def test_break_journey_rejects_sub_hour_connection():
    p = MockProvider()
    none = find_broken_journeys(p, DATE, "JP", "ASV", [TravelClass.SL],
                                min_connection_min=90, max_connection_min=84)
    assert none == []
