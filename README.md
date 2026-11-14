# 📈 Fund Tracker (pooled money, NAV / unit method)

Track money you manage for family, relatives and friends in **one** trading account. Every investor
holds **units**; the fund has one **NAV per unit**. Built on the same design and engine as the personal
Portfolio Tracker (holdings, add-ons, exits, charges, analytics, tax, watchlist), plus investor accounts.

## How the unit method works

| Step | What happens |
|---|---|
| Day one | Your starting capital buys units at the **face value** (₹10). ₹10,00,000 → 1,00,000 units. |
| Someone adds money | They buy units at the **NAV of that day**. Fund worth ₹11,00,000 over 1,00,000 units → NAV ₹11; ₹2,20,000 buys 20,000 units. |
| Someone withdraws | Their units are redeemed at the NAV of that day. "Withdraw everything" redeems all their units. |
| Any day | **NAV = fund value ÷ units outstanding.** Each person's worth = their units × NAV. |

- NAV on a day = (cash + holdings at that day's close − money that moved that day) ÷ units before that day.
  So a deposit or withdrawal never changes the NAV for anyone else, and two flows on the same day get the same NAV.
- The NAV and units of each entry are **frozen** when saved. *Fund & settings → NAV audit* re-prices every
  entry from the trade ledger and closing prices and shows any difference (for example after a back-dated
  trade, or an entry saved during market hours). You choose: apply the recomputed values, or lock the stored ones.
- "Enter the NAV myself" stores a manual, locked NAV for cases where you settled at your own figure.
- Cash can only come from investors (who get units for it) or from selling, so a buy is blocked when the
  fund has no cash, and a withdrawal is blocked when the investor has too few units or the fund too little cash.

## Run locally

```bash
cd fund_tracker
pip install -r requirements.txt
streamlit run app.py
```

- No `secrets.toml` → local dev mode (no sign-in), data in `fund.db` (SQLite) next to `app.py`.
- First run: **Set up your fund** on the Dashboard (your name, starting capital, start date), or
  *Fund & settings → Load sample fund* to explore, then *Delete ALL my data* to start for real.
- Tests: `python tests/test_nav.py` (unit/NAV maths), `python tests/test_core.py` (trade engine),
  `python tests/smoke_dialogs.py` (every write flow on a temp DB), `python tests/smoke_views.py` (all pages).

## Pages

| Page | What it is for |
|---|---|
| Dashboard | Fund value, NAV, units, cash, P&L, XIRR, NAV vs Nifty 50 with money-in/out markers, ownership, alerts |
| Investors | Everyone's units, share %, value, gain, XIRR. Select a person → add money, withdraw, statement (CSV), value chart |
| Holdings / New position / Watchlist | Record buys, add-ons, exits, dividends (same as the Portfolio Tracker) |
| Analytics / Tax | Fund-level performance (driven by NAV), trade quality, risk, capital-gains estimate |
| Fund & settings | Fund name, unit ledger, NAV history CSV, NAV audit, thresholds, links, JSON backup / restore |

## Deploying (Streamlit Cloud + Supabase + Google sign-in)

All tables are prefixed `fund_`, so this app can use the **same Supabase database and the same Google
OAuth client** as the Portfolio Tracker without clashing. Only the redirect URI differs.

1. **GitHub**: push this folder to a **private** repo. `.gitignore` already excludes `secrets.toml` and `fund.db`.
2. **Google OAuth client** (<https://console.cloud.google.com> → APIs & Services → Credentials → your existing
   web client): under *Authorised redirect URIs* add `https://<your-app-name>.streamlit.app/oauth2callback`.
3. **Streamlit Cloud** (<https://share.streamlit.io> → Create app): pick the repo, branch `main`, main file
   `app.py`, and a custom URL that matches the redirect URI above.
4. **Advanced settings → Secrets**: copy the secrets of the Portfolio Tracker app (its *Settings → Secrets*)
   and change one line, `redirect_uri`. Template: `.streamlit/secrets.toml.example`.

```toml
allowed_emails = ["you@gmail.com"]          # only these Google accounts can sign in

[database]
url = "postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"

[auth]
redirect_uri = "https://<your-app-name>.streamlit.app/oauth2callback"
cookie_secret = "<long random string>"

[auth.google]
client_id = "<client id>.apps.googleusercontent.com"
client_secret = "<client secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

5. Deploy, sign in with Google, then **Set up your fund**. Tables are created on first run.

Moving local data online: local app → *Fund & settings → Download full backup (JSON)*, then on the online
app → *Restore from JSON backup*.

> Supabase pauses free projects after 7 days without activity. Opening either app counts as activity.
> Keep `allowed_emails` filled in: with an empty list, anyone with a Google account could create their own fund.

## Known limitations

- Only the manager signs in; investors do not have their own logins (share a statement CSV instead).
- No management or performance fee is charged to investors' units.
- Splits and bonuses must be adjusted manually (edit the buy qty and price), then run the NAV audit.
- Tax is estimated at fund level (the account is in one name); it is not split per investor.

## Layout

```
app.py              entry: auth, navigation, sidebar NAV card
core/nav.py         unit accounting: NAV on a date, units, investor summary, statements, audit
core/db.py          SQLAlchemy models (fund_investors, fund_flows, …) + owner-scoped CRUD, JSON backup
core/ledger.py      FIFO, position summaries, cash ledger, validation
core/analytics.py   daily value history, XIRR, trade stats, tax, alerts
core/state.py       cached loading + shared context (nav, units, investor summary)
core/dialogs.py     investor, money in/out, trade, edit and delete dialogs
views/*.py          one file per page
tests/              engine tests + headless page and dialog smoke tests
```
