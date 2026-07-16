from __future__ import annotations

import json
import urllib.request

FALLBACK_USD_TO_PKR = 278.159897

_cached_rate = None


def get_usd_to_pkr_rate() -> float:
    global _cached_rate
    if _cached_rate is not None:
        return _cached_rate

    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        rate = float(data["rates"]["PKR"])
        _cached_rate = rate
        return rate
    except Exception:
        _cached_rate = FALLBACK_USD_TO_PKR
        return FALLBACK_USD_TO_PKR


def to_pkr(amount: float, currency: str) -> float:
    if currency == "PKR":
        return amount
    if currency == "USD":
        return amount * get_usd_to_pkr_rate()
    return amount