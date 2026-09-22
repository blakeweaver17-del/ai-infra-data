"""Pull reported financials from SEC EDGAR (free, official) for each ticker.

Writes data/financials/<TICKER>.json with quarterly and annual values for key
line items, exactly as filed (no estimates). Companies that don't file with
the SEC in XBRL (some foreign listings) are logged and skipped.

SEC requires a User-Agent with contact info: set SEC_USER_AGENT,
e.g. "Blake Research yourname@example.com".
"""
import json, os, sys, time, datetime as dt, csv
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "financials"
UA = os.environ.get("SEC_USER_AGENT", "").strip()

# line item -> candidate XBRL concepts, in priority order
CONCEPTS = {
    "revenue": ["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:SalesRevenueNet", "ifrs-full:Revenue"],
    "gross_profit": ["us-gaap:GrossProfit", "ifrs-full:GrossProfit"],
    "operating_income": ["us-gaap:OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"],
    "net_income": ["us-gaap:NetIncomeLoss", "ifrs-full:ProfitLoss"],
    "operating_cash_flow": ["us-gaap:NetCashProvidedByUsedInOperatingActivities",
                            "ifrs-full:CashFlowsFromUsedInOperatingActivities"],
    "capex": ["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
              "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "cash": ["us-gaap:CashAndCashEquivalentsAtCarryingValue", "ifrs-full:CashAndCashEquivalents"],
    "long_term_debt": ["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt"],
    "diluted_shares": ["us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_outstanding": ["dei:EntityCommonStockSharesOutstanding"],
}
FORMS = {"10-K", "10-Q", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A"}


def get(url):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"}, timeout=60)
    r.raise_for_status()
    time.sleep(0.15)  # stay well under SEC's 10 requests/second
    return r.json()


def extract(facts, concept):
    tax, name = concept.split(":")
    node = facts.get("facts", {}).get(tax, {}).get(name)
    if not node:
        return None
    rows = []
    for unit, vals in node.get("units", {}).items():
        for v in vals:
            if v.get("form") not in FORMS:
                continue
            rows.append({"start": v.get("start"), "end": v["end"], "val": v["val"], "unit": unit,
                         "fy": v.get("fy"), "fp": v.get("fp"), "form": v["form"], "filed": v["filed"]})
    if not rows:
        return None
    # keep the latest filing for each period (restatements win)
    best = {}
    for r in sorted(rows, key=lambda r: r["filed"]):
        best[(r["start"], r["end"], r["unit"])] = r
    out = sorted(best.values(), key=lambda r: r["end"])
    for r in out:
        if r["start"]:
            days = (dt.date.fromisoformat(r["end"]) - dt.date.fromisoformat(r["start"])).days
            r["period"] = "quarter" if days < 120 else "year" if days > 330 else f"{days}d"
        else:
            r["period"] = "instant"
    return {"concept": concept, "values": out}


def main():
    if not UA or "@" not in UA:
        sys.exit("Set SEC_USER_AGENT to 'Name email@example.com' (SEC requires contact info).")
    OUT.mkdir(parents=True, exist_ok=True)
    tickers = get("https://www.sec.gov/files/company_tickers.json")
    cik_map = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in tickers.values()}
    log = {"run_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z", "ok": [], "skipped": {}}
    with open(ROOT / "universe.csv", newline="") as f:
        uni = list(csv.DictReader(f))
    for m in uni:
        t = m["ticker"]
        if m["tier"] in ("benchmark", "holding"):
            continue
        cik = (m.get("sec_cik") or "").strip().zfill(10) if m.get("sec_cik") else cik_map.get(t.upper())
        if not cik:
            log["skipped"][t] = "no SEC CIK found (may not file with SEC)"
            continue
        try:
            facts = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        except Exception as e:
            log["skipped"][t] = f"fetch failed: {str(e)[:150]}"
            continue
        items = {}
        for item, cands in CONCEPTS.items():
            for c in cands:
                x = extract(facts, c)
                if x:
                    items[item] = x
                    break
        if not items:
            log["skipped"][t] = "no XBRL financials (likely a foreign filer without tagged data)"
            continue
        doc = {"ticker": t, "cik": cik, "entity": facts.get("entityName"), "fetched_at": log["run_at"],
               "source": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", "items": items}
        (OUT / f"{t}.json").write_text(json.dumps(doc, indent=0))
        log["ok"].append(t)
    (ROOT / "data" / "financials_log.json").write_text(json.dumps(log, indent=1))
    print(f"ok={len(log['ok'])} skipped={len(log['skipped'])}")


if __name__ == "__main__":
    main()
