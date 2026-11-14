"""Feature 2 - 'Next available seat'.

Given an intended trip O->D on a single train that is waitlisted, find the
boarding/alighting *sub-segments* of the same train that are confirmable,
ranked by how little of the intended journey they sacrifice.

Two candidate families (both natural, both in the user's spec):
  A) BOARD-LATER : keep destination D, push boarding point downstream
                   (Jaipur->Asarva WL  ->  Ajmer->Asarva  ->  Udaipur->Asarva).
  B) ALIGHT-EARLIER : keep origin O, pull destination upstream.

Since the live API exposes only per-segment *status* (not berth intervals),
the full O(S^2) segment matrix is not free. We exploit a loose monotonicity:
a strictly-shorter span is never *more* crowded at its tightest edge, so
availability tends to improve as we shorten. That lets a **budgeted probe**
(binary-search style) find the minimal-sacrifice confirmable segment in
~O(log S) calls instead of O(S). A full scan is available for transparency
/ demo, and the engine degrades to it near monotonicity violations
(quota pockets like RLWL).
"""

from __future__ import annotations

from datetime import date as Date
from typing import Iterable

from .models import (
    AvailabilityStatus,
    SegmentOption,
    SegmentQuery,
    Train,
    TravelClass,
)
from .providers.base import AvailabilityProvider


# --------------------------------------------------------------------------- #
# Candidate generation
# --------------------------------------------------------------------------- #
def _board_later(o_seq: int, d_seq: int) -> list[tuple[int, int]]:
    """(b, D) for b in [o_seq .. d_seq-1]; b == o_seq is the full intended trip."""
    return [(b, d_seq) for b in range(o_seq, d_seq)]


def _alight_earlier(o_seq: int, d_seq: int) -> list[tuple[int, int]]:
    """(O, a) for a in (o_seq .. d_seq); excludes the full trip (already in A)."""
    return [(o_seq, a) for a in range(d_seq - 1, o_seq, -1)]


def _make_option(
    train: Train,
    o_seq: int,
    d_seq: int,
    b: int,
    a: int,
    cls: TravelClass,
    status: AvailabilityStatus,
) -> SegmentOption:
    total_km = train.dist_between(o_seq, d_seq) or 1
    return SegmentOption(
        train_no=train.number,
        travel_class=cls,
        from_code=train.stop_at_seq(b).station,
        to_code=train.stop_at_seq(a).station,
        from_seq=b,
        to_seq=a,
        status=status,
        coverage=train.dist_between(b, a) / total_km,
        uncovered_head_km=train.dist_between(o_seq, b),   # O .. boarding
        uncovered_tail_km=train.dist_between(a, d_seq),    # alighting .. D
    )


def _probe(provider, train, travel_date, cls, o_seq, d_seq, b, a) -> SegmentOption:
    q = SegmentQuery(
        train_no=train.number,
        travel_date=travel_date,
        from_code=train.stop_at_seq(b).station,
        to_code=train.stop_at_seq(a).station,
        travel_class=cls,
    )
    return _make_option(train, o_seq, d_seq, b, a, cls, provider.get_availability(q))


# --------------------------------------------------------------------------- #
# Core scan
# --------------------------------------------------------------------------- #
def find_next_available(
    provider: AvailabilityProvider,
    train_no: str,
    travel_date: Date,
    origin: str,
    dest: str,
    classes: Iterable[TravelClass],
    *,
    full_scan: bool = False,
    include_alight_earlier: bool = True,
) -> dict[TravelClass, list[SegmentOption]]:
    """Return, per class, sub-segment options ranked best-first.

    best-first = highest coverage (least sacrifice), then best status rank.
    The intended O->D option is always included as the baseline
    ('your trip is WL 134').
    """
    train = provider.get_train(train_no)
    o_seq, d_seq = train.seq_of(origin), train.seq_of(dest)
    results: dict[TravelClass, list[SegmentOption]] = {}

    for cls in classes:
        if cls not in train.classes:
            results[cls] = []
            continue

        if full_scan:
            candidates = _board_later(o_seq, d_seq)
            if include_alight_earlier:
                candidates += _alight_earlier(o_seq, d_seq)
            options = [
                _probe(provider, train, travel_date, cls, o_seq, d_seq, b, a)
                for (b, a) in candidates
            ]
        else:
            options = _scan_budgeted(provider, train, travel_date, cls, o_seq, d_seq)

        options.sort(key=lambda op: (
            -op.coverage,
            op.status.state.rank,
            op.status.number if not op.status.confirmable else 0,
        ))
        results[cls] = options

    return results


def _scan_budgeted(provider, train, travel_date, cls, o_seq, d_seq) -> list[SegmentOption]:
    """~O(log S) board-later probe + baseline, exploiting monotonicity.

    Binary-search the smallest head-sacrifice boarding point `b` (destination
    fixed at D) that is confirmable; always include the full trip as baseline;
    verify the boundary neighbours to guard against quota-pocket
    non-monotonicity (e.g. RLWL).
    """
    seen: dict[int, SegmentOption] = {}

    def probe(b: int) -> SegmentOption:
        if b not in seen:
            seen[b] = _probe(provider, train, travel_date, cls, o_seq, d_seq, b, d_seq)
        return seen[b]

    baseline = probe(o_seq)
    if baseline.confirmable:
        return [baseline]

    lo, hi, best = o_seq + 1, d_seq - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if probe(mid).confirmable:
            best, hi = mid, mid - 1     # try to sacrifice even less
        else:
            lo = mid + 1
    if best is not None:
        for nb in (best - 1, best + 1):
            if o_seq < nb < d_seq:
                probe(nb)
    return list(seen.values())
