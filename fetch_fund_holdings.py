"""Look-through exposure: what each fund you own holds, from official SEC filings.

Every ETF files Form N-PORT with the SEC listing every holding and its % of the
fund. Those filings are public ~60 days after each quarter-end, so weights here
lag by 2-3 months. That's fine for exposure: fund weights drift slowly.

For every ticker with tier "holding" in universe.csv (except IBIT, which holds
only bitcoin and doesn't file N-PORT) this writes:
  data/fund_holdings/<FUND>.json   full holdings list with % of fund
  data/lookthrough.json            {fund: {as_of, source, weights: {TRACKED_TICKER: pct}}}

Tracked companies are matched by ticker when the filing includes one, otherwise
by company name (marked "name" in the output so it can be checked).
Requires SEC_USER_AGENT, e.g. "Blake Research you@example.com".
"""
import csv, json, os, re, sys, time, datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fund_holdings"
UA = os.environ.get("SEC_USER_AGENT", "").strip()
SKIP = {"IBIT"}  # grantor trust holding bitcoin; no N-PORT
# Extra exact names (after normalizing) for companies whose filing name differs from universe.csv
ALIASES = {
    "AMD": ["ADVANCED MICRO DEVICES"], "AMZN": ["AMAZON COM"], "WMB": ["WILLIAMS COS", "WILLIAMS COMPANIES"],
    "SMCI": ["SUPER MICRO COMPUTER"], "MOD": ["MODINE MANUFACTURING"], "DLR": ["DIGITAL REALTY TRUST"],
    "SMR": ["NUSCALE POWER"], "TSM": ["TAIWAN SEMICONDUCTOR MANUFACTURING"], "GOOGL": ["ALPHABET"],
    "ETN": ["EATON"], "KMI": ["KINDER MORGAN"], "SKHY": ["SK HYNIX"], "ASML": ["ASML"],
}


def get(url, as_json=False):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"}, timeout=90)
    r.raise_for_status()
    time.sleep(0.15)
    return r.json() if as_json else r.text


def strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def norm(s):
    s = re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())
    s = re.sub(r"\b(INC|CORP|CORPORATION|CO|LTD|PLC|NV|N V|SA|AG|HOLDINGS|HOLDING|CLASS [A-Z]|THE|COMPANY|GROUP|TECHNOLOGIES|TECHNOLOGY)\b", " ", s)
    return " ".join(s.split())


def latest_nport(series_id):
    """Newest NPORT-P accession number for a fund series."""
    feed = get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series_id}"
               f"&type=NPORT-P&dateb=&owner=include&count=10&output=atom")
    accs = re.findall(r"\b(\d{10}-\d{2}-\d{6})\b", feed)
    if not accs:
        raise ValueError(f"no NPORT-P filings found for series {series_id}")
    return accs[0]


def parse_nport(xml_text):
    root = strip_ns(ET.fromstring(xml_text))
    gen = root.find(".//genInfo")
    as_of = gen.findtext("repPdDate") if gen is not None else None
    series = gen.findtext("seriesId") if gen is not None else None
    rows = []
    for inv in root.iter("invstOrSec"):
        pct = inv.findtext("pctVal")
        if pct is None:
            continue
        ids = inv.find("identifiers")
        ticker = isin = None
        if ids is not None:
            t = ids.find("ticker"); i = ids.find("isin")
            ticker = t.get("value") if t is not None else None
            isin = i.get("value") if i is not None else None
        rows.append({"name": inv.findtext("name") or inv.findtext("title"), "ticker": ticker,
                     "isin": isin, "cusip": inv.findtext("cusip"), "pct": float(pct)})
    rows.sort(key=lambda r: -r["pct"])
    return as_of, series, rows


def main():
    if not UA or "@" not in UA:
        sys.exit("Set SEC_USER_AGENT to 'Name email@example.com'.")
    OUT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "universe.csv", newline="") as f:
        uni = list(csv.DictReader(f))
    funds = [u["ticker"] for u in uni if u["tier"] == "holding" and u["ticker"] not in SKIP]
    tracked = [u for u in uni if u["tier"] not in ("holding", "benchmark")]
    by_ticker = {u["ticker"].upper(): u["ticker"] for u in tracked}
    by_name = {norm(u["name"]): u["ticker"] for u in tracked if norm(u["name"])}
    for t, names in ALIASES.items():
        for n in names:
            by_name[norm(n)] = t

    mf = get("https://www.sec.gov/files/company_tickers_mf.json", as_json=True)
    cols = mf["fields"]  # ["cik","seriesId","classId","symbol"]
    mf_map = {row[cols.index("symbol")].upper(): dict(zip(cols, row)) for row in mf["data"]}

    look, log = {}, {"run_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z", "ok": [], "failed": {}}
    for fund in funds:
        try:
            info = mf_map.get(fund.upper())
            if not info:
                raise ValueError("fund ticker not in SEC fund list")
            cik = str(info["cik"]); series = info["seriesId"]
            acc = latest_nport(series)
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/primary_doc.xml"
            as_of, s_id, rows = parse_nport(get(url))
            if s_id and s_id != series:
                raise ValueError(f"filing series {s_id} != expected {series}")
            weights, matched_by = {}, {}
            for r in rows:
                t = by_ticker.get((r["ticker"] or "").upper())
                how = "ticker"
                if not t:
                    n = norm(r["name"])
                    t = by_name.get(n)  # exact match only, to avoid false matches
                    how = "name"
                if t:
                    weights[t] = round(weights.get(t, 0) + r["pct"], 4)  # e.g. GOOGL + GOOG share classes
                    matched_by[t] = how
            (OUT / f"{fund}.json").write_text(json.dumps(
                {"fund": fund, "as_of": as_of, "source": url, "holdings_count": len(rows),
                 "top_100": rows[:100]}, indent=0))
            look[fund] = {"as_of": as_of, "source": url, "weights": weights, "matched_by": matched_by}
            log["ok"].append(fund)
        except Exception as e:
            log["failed"][fund] = str(e)[:200]
    prev = ROOT / "data" / "lookthrough.json"
    if prev.exists():  # keep last good data for funds that failed this time
        old = json.loads(prev.read_text()).get("funds", {})
        for k, v in old.items():
            look.setdefault(k, v)
    prev.write_text(json.dumps({"generated_at": log["run_at"], "funds": look}, indent=1))
    (ROOT / "data" / "fund_holdings_log.json").write_text(json.dumps(log, indent=1))
    print(f"ok={log['ok']} failed={log['failed']}")


if __name__ == "__main__":
    main()
