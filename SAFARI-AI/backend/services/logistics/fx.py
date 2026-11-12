"""Live exchange rates: the Bank of Tanzania's daily indicative rates.

Driftmark's JSON mirror is read first; when it refuses or fails, the rate table on the Bank of
Tanzania's own page is parsed instead, so the rate stays live.

The feed gives TZS per one unit of each currency (buying, selling, mean). We use the mean. The last good
snapshot is saved in the store, so a failed fetch falls back to it, and only then to the configured
`SAFARI_TZS_PER_USD`, labelled as a fallback.

TANAPA prices non-resident, expatriate and foreign-vehicle fees in USD and bills them in TZS at its own
fixed rate (2,555 in 2026/27). For those rows the exact USD price is the TZS amount divided by that rate,
so `fee_usd` returns that instead of a market conversion.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone

from services.common.models import Record
from services.sources.http import Http

log = logging.getLogger("safari.fx")

FEED_URL = "https://www.driftmark.co.tz/exchange-rates/api/latest.json"
BOT_URL = "https://www.bot.go.tz/ExchangeRate/excRates"
SOURCE_ID = "bot_fx"
RECORD_KIND = "fx_rates"
TTL_SECONDS = 3600.0
USD_PRICED_CLASSES = {"non_resident", "expatriate", "foreign_vehicle"}


class LiveFx:
    def __init__(self, store, fallback_tzs_per_usd: float, http: Http | None = None, ttl: float = TTL_SECONDS) -> None:
        self.store = store
        self.fallback = fallback_tzs_per_usd
        self.http = http
        self.ttl = ttl
        self._lock = threading.Lock()
        self._snapshot: dict | None = None
        self._fetched = 0.0

    # Public ---------------------------------------------------------------

    def snapshot(self) -> dict:
        """{date, rates: {CODE: mean}, source, source_url, live, fetched_at}. Never raises."""
        with self._lock:
            if self._snapshot and time.monotonic() - self._fetched < self.ttl:
                return self._snapshot
            fresh = self._fetch()
            if fresh:
                self._snapshot, self._fetched = fresh, time.monotonic()
                return fresh
            if self._snapshot:  # keep serving the last good one, retry after a short pause
                self._fetched = time.monotonic() - self.ttl + 300
                return self._snapshot
            saved = self._saved()
            if saved:
                self._snapshot, self._fetched = saved, time.monotonic() - self.ttl + 300
                return saved
            return {
                "date": None,
                "rates": {"USD": self.fallback},
                "source": f"Fallback rate from settings ({self.fallback:g} TZS per USD); the live feed could not be reached",
                "source_url": BOT_URL,
                "live": False,
                "fetched_at": None,
            }

    def rate(self, code: str = "USD") -> float | None:
        """TZS per one unit of `code`."""
        code = code.upper()
        if code == "TZS":
            return 1.0
        return self.snapshot()["rates"].get(code)

    def to(self, amount_tzs: float, code: str = "USD") -> float | None:
        rate = self.rate(code)
        return round(amount_tzs / rate, 2) if rate else None

    def convert(self, amount: float, source: str, target: str) -> dict:
        source, target = source.upper(), target.upper()
        snap = self.snapshot()
        rates = {"TZS": 1.0, **snap["rates"]}
        missing = [code for code in (source, target) if code not in rates]
        if missing:
            return {"error": f"No Bank of Tanzania rate for {', '.join(missing)}", "currencies": sorted(rates)}
        tzs = amount * rates[source]
        return {
            "amount": amount,
            "from": source,
            "to": target,
            "result": round(tzs / rates[target], 2),
            "tzs_per_unit": {code: round(rates[code], 4) for code in {source, target} if code != "TZS"},
            "rate_date": snap["date"],
            "live": snap["live"],
            "source": snap["source"],
            "source_url": snap["source_url"],
        }

    def meta(self) -> dict:
        snap = self.snapshot()
        return {
            "usd": round(snap["rates"].get("USD") or 0, 2),
            "date": snap["date"],
            "live": snap["live"],
            "source": snap["source"],
            "source_url": snap["source_url"],
        }

    def refresh(self) -> dict:
        with self._lock:
            self._fetched = 0.0
        snap = self.snapshot()
        return {"status": "ok" if snap["live"] else "error", "date": snap["date"], "usd": snap["rates"].get("USD")}

    # Internals ------------------------------------------------------------

    def _fetch(self) -> dict | None:
        client = self.http or Http(timeout=15.0, retries=1)
        started = _now()
        errors = []
        snap = None
        try:
            for reader in (_read_feed, _read_bot_page):
                try:
                    snap = reader(client, started)
                    break
                except Exception as exc:  # network, refusal, JSON or table changes
                    errors.append(f"{reader.__name__.strip('_')}: {exc}"[:200])
        finally:
            if self.http is None:
                client.close()
        if snap is None:
            log.warning("exchange-rate sources failed: %s", "; ".join(errors))
            self._status({"status": "error", "error": "; ".join(errors)[:300], "last_attempt": started})
            return None
        try:
            self.store.replace_records(RECORD_KIND, [Record(RECORD_KIND, "latest", snap, SOURCE_ID, snap["feed"], started)])
        except Exception as exc:
            log.warning("could not save exchange rates: %s", exc)
        self._status(
            {
                "status": "ok",
                "error": "; ".join(errors)[:300] or None,
                "last_attempt": started,
                "last_success": started,
                "records": {"currencies": len(snap["rates"]), "rate_date": snap["date"], "via": snap["feed"]},
            }
        )
        return snap

    def _saved(self) -> dict | None:
        records = self.store.list_records(RECORD_KIND)
        if not records:
            return None
        saved = dict(records[0].payload)
        saved["live"] = False
        saved["source"] = f"Bank of Tanzania rates of {saved.get('date')} (saved copy; the live feed could not be reached)"
        return saved

    def _status(self, status: dict) -> None:
        try:
            self.store.set_source_status(SOURCE_ID, {"name": "Bank of Tanzania exchange rates", "url": BOT_URL, **status})
        except Exception:
            pass


def _read_feed(client: Http, started: str) -> dict:
    raw = client.json(FEED_URL)
    rates = {
        str(row["code"]).upper(): float(row["mean"])
        for row in raw.get("rates", [])
        if row.get("code") and isinstance(row.get("mean"), (int, float)) and row["mean"] > 0
    }
    if "USD" not in rates:
        raise ValueError("feed has no USD rate")
    return _snapshot(raw.get("date"), rates, raw.get("source_url") or BOT_URL, raw.get("fetched_at") or started, FEED_URL)


_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def _read_bot_page(client: Http, started: str) -> dict:
    """The table on bot.go.tz: S/NO, currency, buying, selling, mean, trade date (e.g. 12-Nov-26)."""
    html = client.get(BOT_URL).text
    rates, dates = {}, set()
    for row in _ROW.findall(html):
        cells = [re.sub(r"<[^>]+>", "", cell).strip() for cell in _CELL.findall(row)]
        if len(cells) < 6 or not re.fullmatch(r"[A-Z]{3}", cells[1]):
            continue
        try:
            mean = float(cells[4].replace(",", ""))
        except ValueError:
            continue
        if mean > 0:
            rates[cells[1]] = mean
            dates.add(cells[5])
    if "USD" not in rates:
        raise ValueError("no USD row in the Bank of Tanzania table")
    trade_date = None
    for text in sorted(dates):
        try:
            trade_date = max(trade_date or "", datetime.strptime(text, "%d-%b-%y").date().isoformat())
        except ValueError:
            continue
    return _snapshot(trade_date, rates, BOT_URL, started, BOT_URL)


def _snapshot(day: str | None, rates: dict, source_url: str, fetched_at: str, feed: str) -> dict:
    return {
        "date": day,
        "rates": rates,
        "source": "Bank of Tanzania indicative rates (mean of buying and selling)",
        "source_url": source_url,
        "live": True,
        "fetched_at": fetched_at,
        "feed": feed,
    }


def fee_usd(amount_tzs: float, visitor: str, fx: LiveFx | None, tanapa_rate: float) -> tuple[float | None, str]:
    """USD for a TANAPA fee row: TANAPA's own USD price when the row is USD-priced, else the live rate."""
    if visitor in USD_PRICED_CLASSES and tanapa_rate and abs(amount_tzs / tanapa_rate - round(amount_tzs / tanapa_rate, 2)) < 1e-6:
        return round(amount_tzs / tanapa_rate, 2), "tanapa"
    if fx is not None:
        return fx.to(amount_tzs, "USD"), "live"
    return (round(amount_tzs / tanapa_rate, 2) if tanapa_rate else None), "fixed"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
