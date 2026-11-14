# railengine

A rail-journey planning core for two features on top of an IRCTC-style
availability source:

1. **Break my journey** — split an O→D trip across multiple trains at a
   transfer station, with a connection gap ≥ 1 hour, minimizing breaks then
   wait.
2. **Next available seat** — when the through journey is waitlisted, find the
   boarding/alighting sub-segments of the *same train* that are confirmable
   (per selected class), ranked by how little of the trip they sacrifice.

Both run offline today on a synthetic Jaipur→Asarva corridor:

```bash
python -m railengine.demo        # no API key needed
python -m pytest -q              # 12 tests
```

---

## 1. Why this is one system, not two

Seats are **segment-based inventory**: a reservation holds a berth over a
half-open span `[board, alight)` of the route. The availability of any
sub-segment `(b, a)` is governed by the *tightest* edge it crosses:

```
available(b, a) = capacity − max_{edge ∈ [b, a)} occupancy(edge)
```

This is why **Jaipur→Asarva can be WL-134 while Udaipur→Asarva is AVBL-3** —
the shorter span avoids the crowded Jaipur–Ajmer–Udaipur edges.

The consequence: *"next available seat"* often leaves an **uncovered head
leg** (board at Udaipur ⇒ Jaipur→Udaipur has no seat). *"Break my journey"*
is exactly the engine that fills that leg with another train. So the two
features share one availability engine and compose:

```
            ┌──────────────────────────────┐
            │     AvailabilityProvider      │   Mock | LiveApi
            │   (b, a, class, date) → status│
            └───────────────┬──────────────┘
          ┌─────────────────┴─────────────────┐
   next_seat.py                           journey.py
   Feature 2: segment scan                Feature 1: break routing
   (same train, shift boarding)           (multi-train, min breaks)
```

## 2. Architecture / modules

| Module | Responsibility |
|---|---|
| `models.py` | Domain types: `Train`/`TrainStop`, `TravelClass`, normalized `AvailabilityStatus` (`StatusState` enum), query/result value objects. |
| `availability.py` | Parse raw IRCTC strings (`GNWL 134/WL 120`, `RAC 12`, `CURR_AVBL-0005`, `REGRET/WL`) → normalized status. Everything above works on normalized status only. |
| `providers/base.py` | `AvailabilityProvider` interface — the single seam between engines and data. |
| `providers/mock.py` | Offline corridor. Ground truth is a per-edge occupancy profile; the engine only sees the resulting **status strings**, exactly as a live API would return. |
| `providers/live.py` | Adapter for a real HTTP API (host/auth/JSON shape isolated here; schedules delegated to a cacheable source). |
| `next_seat.py` | Feature 2. |
| `journey.py` | Feature 1 (single-break; RAPTOR-ready). |
| `demo.py` | Runs the Jaipur→Asarva scenario. |

## 3. Algorithms & complexity

**Feature 2 — next available seat.** Two candidate families:
*board-later* (fix destination, push boarding downstream) and *alight-earlier*
(fix origin, pull destination upstream). Because the live API exposes only
per-segment *status* (not berth intervals), the full `O(S²)` segment matrix
is not free, so the default is a **budgeted probe**: a shorter span is never
*more* crowded at its tightest edge, so availability is loosely monotone in
span length — binary-search the smallest-sacrifice confirmable boarding point
in **~O(log S)** API calls instead of **O(S)**, with a neighbour check to
guard against quota-pocket non-monotonicity (RLWL). (`full_scan=True` queries
all candidates for transparency.) In the demo: full scan = 7 calls, budgeted
probe = 4 — same answer.

> If you later get **berth-level data** instead of only published statuses,
> the exact engine is a sweep-line: one pass builds `occupancy[]` along the
> route, a range-max structure answers every sub-segment in `O(1)`–`O(log S)`.
> `MockProvider` already computes ground truth this way.

**Feature 1 — break my journey.** Time-expanded transfer search. A leg joins
the next only at a shared station with `dep(next) − arr(prev) ≥ MCT` (60 min),
and each leg must be seat-feasible in a chosen class (reuses Feature 2's
engine). Ranked by `(breaks, total wait, arrival)`. The prototype implements
the **single-break** case; the k-break generalization is RAPTOR
(round k = k transfers, Pareto arrival-time vs. transfers) — the interfaces
are shaped for a mechanical drop-in.

## 4. Going live

`LiveApiProvider` reads config from the environment and leaves engine code
untouched:

```bash
export RAIL_API_BASE="https://<your-irctc-style-host>"
export RAIL_API_KEY="…"
export RAIL_API_HOST="<rapidapi-host>"   # optional
```

```python
from railengine import LiveApiProvider, MockProvider, find_next_available
# schedules change rarely → serve them from a cached/static source:
provider = LiveApiProvider(schedule_source=MockProvider())
```

Only `_fetch` / `_map_response` in `providers/live.py` are endpoint-specific.
TLS/proxy are honored via the environment — do not disable verification.

## 5. Roadmap

- [ ] Static schedule store (GTFS-like) to replace mock schedules in live mode.
- [ ] RAPTOR multi-break routing (k ≥ 2) with Pareto results.
- [ ] Response cache + rate-limit/backoff in `LiveApiProvider`.
- [ ] Confirmation-probability model (historical WL→CNF movement) to rank WL options.
- [ ] HTTP API / UI surface over the two engines.
