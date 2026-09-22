# ai-infra-data

Long-term market data for the Picks & Shovels AI infrastructure research system.

GitHub Actions saves daily closing prices and weekly SEC financials into this repo. Git history keeps a dated, permanent record of every day's data.

**This repo holds public market data only.** Keep positions, cost basis and the journal out of it; those live in the private research site on claude.ai.

## What's here

| Path | What it is | Updated |
|---|---|---|
| `universe.csv` | Master list of tickers, layers and tiers. Edit this to add or remove companies. | By you |
| `data/prices/<TICKER>.csv` | Daily price history back to 2015 (open, high, low, close, adjusted close, volume) | Weekdays after the close |
| `data/latest.json` | Latest prices, 1D/5D/1M/YTD/1Y changes, 52-week range, and flags for big moves (5%+ in a day, 10%+ in a week) | Weekdays after the close |
| `data/financials/<TICKER>.json` | Revenue, gross profit, operating income, net income, operating cash flow, capex, cash, debt, shares, as filed with the SEC | Saturdays |
| `data/fund_holdings/<FUND>.json` | What each fund you own holds, from its official SEC filing (Form N-PORT). Lags 2–3 months. | Monthly (15th) |
| `data/lookthrough.json` | Each fund's % in every tracked company — used for look-through exposure | Monthly |
| `index.html` | Viewer: table, price charts, financials | Reads the data files |

## One-time setup (about 15 minutes)

1. **Create the repo.** On GitHub, create a new **public** repository named `ai-infra-data`. Upload everything in this folder, keeping the `.github` folder (it's hidden on Mac; press Cmd+Shift+. in Finder to see it).
   Why public: Claude can then read the data without a password, and it contains nothing personal.
2. **Let Actions save data.** Go to Settings → Actions → General → Workflow permissions, choose **Read and write permissions**, and click Save.
3. **Add your SEC contact.** Go to Settings → Secrets and variables → Actions → New repository secret. Name it `SEC_USER_AGENT` and give it a value like `Blake Research you@example.com`. The SEC requires contact info on automated requests.
4. **Optional: paid price data.** Prices come from yfinance by default. It's free but unofficial, so it can break without warning. For something sturdier, sign up for Tiingo and add a secret named `TIINGO_API_KEY`. The script switches automatically; check Tiingo's current free and paid limits before choosing.
5. **Backfill.** Go to the Actions tab, open **daily-prices**, and click **Run workflow**. The first run downloads history back to 2015 and takes a few minutes. Then run **weekly-financials** and **monthly-fund-holdings** once the same way.
6. **Turn on the viewer.** Go to Settings → Pages, set Source to **Deploy from a branch**, pick `main` and `/ (root)`, and save. The site appears at `https://<your-username>.github.io/ai-infra-data/`.

## Maintenance

- **Add a company:** add a row to `universe.csv`. The next run backfills its history.
- **A run failed:** open the Actions tab. `data/fetch_log.json` lists which tickers failed and why. History is never erased by a failed run.
- **Schedules stopped:** GitHub can pause scheduled workflows in repos with no activity. The daily data commits normally keep it active, but if data stops updating, check the Actions tab and re-enable the workflow.
- **Timing:** schedules run in UTC (21:30 UTC is 5:30 pm ET in summer, 4:30 pm ET in winter) and can start late when GitHub is busy.
- **Foreign companies** (TSM, ASML, SKHY, ARM) file with the SEC differently, so some financials may be missing. Prices still work.
