"""Append daily price history for every ticker in universe.csv.

History is never overwritten with empty data: new rows are merged by date.
Writes:
  data/prices/<TICKER>.csv   date,open,high,low,close,adj_close,volume
  data/latest.json           snapshot + move flags used by the daily review
  data/fetch_log.json        what succeeded / failed on the last run

Provider: yfinance by default (free, unofficial - can break).
If a TIINGO_API_KEY environment variable is set, Tiingo is used instead.
"""
import csv, json, os, sys, time, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "data" / "prices"
START_DATE = "2015-01-01"          # first backfill goes back this far
OVERLAP_DAYS = 7                   # re-fetch recent days to catch corrections
FIELDS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
MOVE_1D, MOVE_5D = 5.0, 10.0       # % thresholds for flags


def universe():
    with open(ROOT / "universe.csv", newline="") as f:
        return list(csv.DictReader(f))


def load_history(t):
    p = PRICES / f"{t}.csv"
    if not p.exists():
        return {}
    with open(p, newline="") as f:
        return {r["date"]: r for r in csv.DictReader(f)}


def save_history(t, rows):
    PRICES.mkdir(parents=True, exist_ok=True)
    with open(PRICES / f"{t}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for d in sorted(rows):
            w.writerow({k: rows[d].get(k, "") for k in FIELDS})


def fetch_yfinance(t, start):
    import yfinance as yf
    df = yf.Ticker(t).history(start=start, auto_adjust=False, actions=False)
    out = {}
    for idx, r in df.iterrows():
        d = idx.strftime("%Y-%m-%d")
        out[d] = {"date": d, "open": round(float(r["Open"]), 4), "high": round(float(r["High"]), 4),
                  "low": round(float(r["Low"]), 4), "close": round(float(r["Close"]), 4),
                  "adj_close": round(float(r.get("Adj Close", r["Close"])), 4), "volume": int(r["Volume"])}
    return out


def fetch_tiingo(t, start):
    import requests
    key = os.environ["TIINGO_API_KEY"]
    url = f"https://api.tiingo.com/tiingo/daily/{t.lower()}/prices"
    r = requests.get(url, params={"startDate": start, "token": key}, timeout=30)
    r.raise_for_status()
    out = {}
    for x in r.json():
        d = x["date"][:10]
        out[d] = {"date": d, "open": x["open"], "high": x["high"], "low": x["low"], "close": x["close"],
                  "adj_close": x["adjClose"], "volume": x["volume"]}
    return out


def pct(a, b):
    return None if not a or not b else round((a / b - 1) * 100, 2)


def snapshot(t, meta, rows):
    ds = sorted(rows)
    if len(ds) < 2:
        return None
    c = lambda i: float(rows[ds[i]]["adj_close"] or rows[ds[i]]["close"])
    last = c(-1)
    last_date = dt.date.fromisoformat(ds[-1])
    def back(days):
        target = (last_date - dt.timedelta(days=days)).isoformat()
        prior = [d for d in ds if d <= target]
        return float(rows[prior[-1]]["adj_close"] or rows[prior[-1]]["close"]) if prior else None
    ytd_base = [d for d in ds if d < f"{last_date.year}-01-01"]
    yr = [float(rows[d]["close"]) for d in ds if d >= (last_date - dt.timedelta(days=365)).isoformat()]
    s = {
        "ticker": t, "name": meta["name"], "layer": meta["layer"], "tier": meta["tier"],
        "date": ds[-1], "close": float(rows[ds[-1]]["close"]),
        "chg_1d": pct(last, c(-2)), "chg_5d": pct(last, c(-6) if len(ds) > 5 else None),
        "chg_1m": pct(last, back(30)), "chg_1y": pct(last, back(365)),
        "chg_ytd": pct(last, float(rows[ytd_base[-1]]["adj_close"] or rows[ytd_base[-1]]["close"]) if ytd_base else None),
        "high_52w": max(yr) if yr else None, "low_52w": min(yr) if yr else None,
    }
    s["from_52w_high"] = pct(s["close"], s["high_52w"])
    flags = []
    if s["chg_1d"] is not None and abs(s["chg_1d"]) >= MOVE_1D: flags.append(f"1-day move {s['chg_1d']}%")
    if s["chg_5d"] is not None and abs(s["chg_5d"]) >= MOVE_5D: flags.append(f"5-day move {s['chg_5d']}%")
    s["flags"] = flags
    return s


def main():
    fetch = fetch_tiingo if os.environ.get("TIINGO_API_KEY") else fetch_yfinance
    log = {"run_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
           "provider": fetch.__name__.replace("fetch_", ""), "ok": [], "failed": {}}
    snaps = []
    for meta in universe():
        t = meta["ticker"]
        hist = load_history(t)
        start = START_DATE
        if hist:
            start = (dt.date.fromisoformat(max(hist)) - dt.timedelta(days=OVERLAP_DAYS)).isoformat()
        try:
            new = fetch(t, start)
            if not new:
                raise ValueError("provider returned no rows")
            hist.update(new)
            save_history(t, hist)
            log["ok"].append(t)
        except Exception as e:  # keep going; never wipe history
            log["failed"][t] = str(e)[:200]
        s = snapshot(t, meta, hist) if hist else None
        if s:
            snaps.append(s)
        time.sleep(0.3)
    out = {"generated_at": log["run_at"], "move_thresholds": {"1d": MOVE_1D, "5d": MOVE_5D},
           "flagged": [s["ticker"] for s in snaps if s["flags"]], "tickers": snaps}
    (ROOT / "data" / "latest.json").write_text(json.dumps(out, indent=1))
    (ROOT / "data" / "fetch_log.json").write_text(json.dumps(log, indent=1))
    print(f"ok={len(log['ok'])} failed={len(log['failed'])} flagged={out['flagged']}")
    if not log["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
