"""Live currency-exchange-rate fetching and conversion to PKR.

RACI hourly rates in the source process JSON arrive in whatever currency
the linked job record specifies (PKR, USD, EUR, GBP, ...). Every cost
figure downstream (``metrics.py``, ``heuristics.py``) sums these rates
directly, so they must already share one common unit before that math
happens. This module is that normalization step: it fetches USD-based
rates once, caches them in memory, and converts any amount to PKR.

Rates come from open.er-api.com and are cached for ``FX_CACHE_TTL_SECONDS``
so a request never blocks on the network more than once per that window.
If the live fetch fails for any reason (network down, API outage,
timeout), a hardcoded snapshot is used instead and a warning is logged -
a redesign request should never fail just because FX rates couldn't be
fetched, including during a live demo on unreliable network.
"""

import json
import logging
import time
import urllib.request

logger = logging.getLogger(__name__)

FX_API_URL = "https://open.er-api.com/v6/latest/USD"
FX_CACHE_TTL_SECONDS = 24 * 60 * 60
FX_FETCH_TIMEOUT_SECONDS = 5

# Snapshot sourced from a real fetch against FX_API_URL on 2026-07-15, used
# whenever the live API is unreachable so a redesign request never fails
# just because FX rates couldn't be fetched.
FALLBACK_RATES = {
    "USD": 1.0,
    "PKR": 278.211558,
    "EUR": 0.875764,
    "GBP": 0.747014,
}

_cache: dict = {"rates": None, "fetched_at": 0.0}


def _fetch_live_rates() -> dict:
    with urllib.request.urlopen(FX_API_URL, timeout=FX_FETCH_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read())
    rates = payload.get("rates")
    if not isinstance(rates, dict) or "USD" not in rates:
        raise ValueError("FX API response is missing a usable 'rates' dict.")
    return rates


def get_rates(force_refresh: bool = False) -> dict:
    """Return the current USD-based rates dict, fetching/caching as needed.

    Serves from the in-memory cache while it is younger than
    ``FX_CACHE_TTL_SECONDS``. On a cold or stale cache, attempts one live
    fetch; if that fetch fails for any reason, logs a warning and falls
    back to :data:`FALLBACK_RATES`, caching that fallback for the same TTL
    so a network outage costs at most one fetch attempt per window rather
    than one per request.
    """
    now = time.time()
    if not force_refresh and _cache["rates"] is not None and (now - _cache["fetched_at"]) < FX_CACHE_TTL_SECONDS:
        return _cache["rates"]

    try:
        rates = _fetch_live_rates()
    except Exception as exc:
        logger.warning(
            "Live FX rate fetch from %s failed (%s); falling back to hardcoded snapshot rates.",
            FX_API_URL, exc,
        )
        rates = FALLBACK_RATES

    _cache["rates"] = rates
    _cache["fetched_at"] = now
    return rates


def convert_to_pkr(amount: float, from_currency: str) -> float:
    """Convert ``amount`` in ``from_currency`` to PKR.

    ``from_currency == "PKR"`` is a no-op passthrough (no rate lookup, no
    rounding drift). Otherwise converts via USD using the cached
    USD-based rates: ``amount_in_usd = amount / rates[from_currency]``,
    then ``amount_in_pkr = amount_in_usd * rates["PKR"]``.

    Raises ``ValueError`` naming the offending code if ``from_currency``
    is not present in the rates table.
    """
    if from_currency == "PKR":
        return amount

    rates = get_rates()
    if from_currency not in rates:
        raise ValueError(f"Unknown or unsupported currency code: {from_currency!r}")
    if "PKR" not in rates:
        raise ValueError("FX rates source has no 'PKR' entry; cannot convert.")

    amount_in_usd = amount / rates[from_currency]
    return amount_in_usd * rates["PKR"]
