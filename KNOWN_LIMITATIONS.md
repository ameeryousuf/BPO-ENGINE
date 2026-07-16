# Known Limitations

This document tracks limitations that are understood and intentionally out
of scope for the current iteration of the redesign engine, so they aren't
mistaken for oversights. See `backend/app/` for the implementation these
notes refer to.

## ~~Cost calculation mixes currencies without conversion~~ (fixed)

Every `jobTasks[].job` entry in the input JSON carries a `currencyType`
(seen in the sample data as `PKR`, `USD`, `EUR`, and `GBP` on the same
process — see `backend/app/data/asIsProcess.json`). This used to be
ignored, so `cost` was a meaningless sum of raw numbers across
currencies rather than a true monetary total.

Fixed: `backend/app/core/fx.py` fetches live USD-based exchange rates
from open.er-api.com, caches them in memory for 24h (matching the API's
own refresh cadence), and falls back to a hardcoded rate snapshot — with
a logged warning — if the live fetch fails for any reason, so a
`/redesign` request never fails just because the FX API is unreachable.
`backend/app/core/parser.py` reads each job's `currencyType` and converts
its `hourlyRate` to PKR via `fx.convert_to_pkr` once, at parse time
(`build_graph`, called once per request), before the value ever reaches
`metrics.py` or `heuristics.py` — both continue summing a single already-
normalized number exactly as before, with no currency-awareness added
downstream. The chosen output/base currency is PKR.

One consequence worth noting: because currency-mixing previously
distorted which tasks *looked* most expensive relative to each other,
rate-sensitive heuristics (`outsourcing`, `extra_resources`,
`centralization`) now target genuinely-expensive tasks instead of
artifacts of unit confusion. On `asIsProcess.json` this held cycle-time
improvement exactly constant (currency has nothing to do with time) but
measurably changed the cost-improvement percentage the RL agent
converges to (roughly 41% pre-fix vs roughly 28% post-fix) — the
pre-fix percentage was optimizing against numbers that were never
real money.

## No authentication or per-tenant isolation

`POST /redesign` is unauthenticated and stateless: any caller can submit
any process JSON and get a result back. There is no concept of a tenant,
user, or API key anywhere in the request path. This is fine for a single
developer or a demo, but is a hard blocker before this can be exposed as
a multi-user SaaS endpoint. Planned future work, not implemented here per
scope: an auth layer (API keys or OAuth/JWT, depending on how the product
integrates), and, if usage/results ever need to persist, per-tenant
scoping of that storage.

## No rate limiting

Nothing currently caps how often a given caller can hit `/redesign`. Each
request runs a bounded but non-trivial RL training loop (2000 episodes,
capped by the new `TRAINING_TIMEOUT_SECONDS` guard and the 200-task input
cap — see `backend/app/core/parser.py` and `backend/app/api/redesign.py`),
so without rate limiting a single caller can still consume a
disproportionate share of server CPU by firing requests back-to-back.
Planned future work: a per-key/per-IP rate limit (e.g. token bucket) at
the API gateway or middleware layer.

## No database persistence

Every request is processed entirely in memory and the result is returned
directly in the HTTP response; nothing is written to disk or a database.
This means there is no request history, no way to revisit a past
redesign, and no audit trail. That's an intentional simplification for
now — adding persistence pulls in schema design, migrations, and storage
choices that are out of scope for this pass. Planned future work: a
datastore (relational, given the shape of the data) for request/response
history once the product needs it.

## Residual timeout-guard caveat

The hard timeout added around training (`TRAINING_TIMEOUT_SECONDS` in
`backend/app/api/redesign.py`) bounds how long the *client* waits — it
does not forcibly kill the underlying worker thread, because Python has
no safe way to cancel an arbitrary running thread. A request that blows
past the timeout will still return a prompt `500` to the caller, but the
abandoned training run keeps consuming a thread-pool worker in the
background until it finishes on its own. The 200-task input cap and the
45-second timeout keep this window small in practice. A future move to a
worker-process pool (rather than a thread pool) would allow genuinely
killing runaway jobs, at the cost of IPC overhead for passing the graph
across the process boundary.
