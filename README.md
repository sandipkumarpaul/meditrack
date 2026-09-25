# MediTrack: Family Medication & Dose Adherence Tracker

A self-hosted Flask web app for keeping track of a whole household's medicines: who takes what and when, whether today's doses have been taken, and when a bottle is about to run out.

[![Tests](https://github.com/sandipkumarpaul/meditrack/actions/workflows/tests.yml/badge.svg)](https://github.com/sandipkumarpaul/meditrack/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-D71F00)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3?logo=bootstrap&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

![Dashboard](docs/screenshots/dashboard.png)

## Why I built it

In many households one person ends up managing medicines for parents, grandparents and children at the same time. Paper charts and phone alarms don't tell you whether Grandpa already took his evening pill, and nobody notices the blood-pressure tablets are almost gone until they are. MediTrack keeps all of that in one place, with one account for the family and a separate profile for each member.

## Features

**Tracking doses**
- Family profiles (Self, Mom, Dad, Grandparent, Child and so on) under a single account, each with its own medication cards
- Large 60 px `+` / `−` stepper buttons that log a dose over AJAX without reloading the page
- A progress bar for each medication that turns green once the day's target is reached
- Counters reset automatically at local midnight in the configured timezone. The full history is kept.
- A "behind schedule" hint when a scheduled time slot has passed and no dose was logged

**Inventory and safety**
- Stock goes down automatically as doses are logged, and undoing a dose puts the pill back
- A low-stock banner plus one-click **+30 / +60 / +90** refills
- Time-slot tags (Morning, Afternoon, Evening, Night, Bedtime, As Needed), categories, prescribing doctor and instructions
- Completed courses (a 7-day antibiotic, say) can be archived without losing their history
- Deleting a profile or medication requires typing its name, and the server checks it again

**History and reports**
- An audit trail of every dose, undo and refill, filterable by family member and action type
- A 14-day adherence chart (Chart.js)
- Export to **Excel (.xlsx)** with formatting, or to **CSV**
- A printable **Doctor Visit Summary** to bring to appointments or save as a PDF
- A full account backup as JSON

**Reminders**
- Browser **Web Push** notifications (VAPID) through a service worker, with a PWA manifest
- A cron webhook that sends reminders for doses that are due and skips doses already taken
- Low-stock alerts are sent at most once per day for each medication
- Per-profile toggles for morning, afternoon and night reminders and for low-stock alerts

**MedEx autofill (Bangladesh)**
- Search [medex.com.bd](https://medex.com.bd) from the "Add Medication" form and autofill the brand name, category, strip or box pill count, suggested dosing frequency and administration notes

<table>
  <tr>
    <td><img src="docs/screenshots/history.png" alt="Dose history and adherence chart"></td>
    <td><img src="docs/screenshots/summary.png" alt="Printable doctor visit summary"></td>
  </tr>
  <tr>
    <td align="center"><em>Dose history &amp; 14-day adherence chart</em></td>
    <td align="center"><em>Printable doctor visit summary</em></td>
  </tr>
</table>

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Python, Flask 3 (blueprints, app factory), Flask-SQLAlchemy, Flask-Login |
| Security | Flask-WTF (CSRF), Flask-Limiter (rate limiting), Werkzeug password hashing |
| Database | SQLite by default, MySQL via PyMySQL |
| Frontend | Jinja2 templates, Bootstrap 5, Bootstrap Icons, vanilla JS (`fetch`), Chart.js |
| Notifications | Web Push API, service worker, `pywebpush` (VAPID) |
| Integrations | `requests` + BeautifulSoup scraper for MedEx, `openpyxl` for Excel export |
| Testing | pytest (34 tests), GitHub Actions CI |

## Getting started

**Requirements:** Python 3.10+

```bash
git clone https://github.com/sandipkumarpaul/meditrack.git
cd meditrack

python -m venv venv
# Windows: venv\Scripts\activate    macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:5000> and create an account.

### Try it with demo data

```bash
python scripts/seed_demo.py
```

This creates a sample household with three family members, seven medications and two weeks of dose history. Log in with **`demo` / `demo1234`**.

### Configuration

The app works without any configuration. To change the defaults, copy `.env.example` to `.env` and edit it:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | random, saved to `.secret_key` | Flask session signing key |
| `DATABASE_URL` | `sqlite:///meditrack.db` | Any SQLAlchemy URL, e.g. `mysql+pymysql://user:pass@localhost:3306/meditrack_db` |
| `APP_TIMEZONE` | `Asia/Dhaka` | Household timezone used for daily resets, reminder slots and displayed times |
| `CRON_SECRET_TOKEN` | random, saved to `.cron_secret` | Shared secret for the reminder webhook |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | generated on first run | Web Push keys |
| `VAPID_CLAIMS_EMAIL` | `admin@meditrack.local` | Contact email sent to push services |
| `PORT` / `FLASK_DEBUG` | `5000` / off | Dev server port and debug mode |

Any secret you don't set is generated the first time the app runs and saved to a local file. Those files are listed in `.gitignore` and must not be committed.

<details>
<summary><strong>Using MySQL instead of SQLite</strong></summary>

```sql
CREATE DATABASE meditrack_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

```env
DATABASE_URL=mysql+pymysql://<user>:<password>@localhost:3306/meditrack_db
```

Tables are created automatically on startup.
</details>

### Setting up reminders

1. Open **Notifications** in the app and click **Enable Browser Notifications**. Web Push only works on `localhost` or over HTTPS.
2. Copy the **cron webhook URL** shown on that page.
3. Point a scheduler such as [cron-job.org](https://cron-job.org), a system crontab or GitHub Actions at that URL a few times a day (for example 08:00, 14:00, 20:00 and 22:00 local time). With the default `slot=auto`, the endpoint works out whether it is morning, afternoon, evening or night, and notifies only about doses that haven't been taken yet.

## Running tests

```bash
pytest
```

The tests use an in-memory SQLite database and cover authentication, profiles, medications, the dose stepper, daily resets, the CSV/Excel/JSON exports, the reminder engine and the security fixes listed below. None of them need network access.

## Project structure

```
├── app/
│   ├── __init__.py          # App factory: extensions, blueprints, error handlers
│   ├── models.py            # User, Profile, Medication, DoseLog, PushSubscription
│   ├── routes/
│   │   ├── auth.py          # Sign-up, login, account settings, backup, deletion
│   │   └── main/            # Dashboard, profiles, medications, history, MedEx, notifications, PWA
│   ├── services/
│   │   ├── medex.py         # MedEx search/detail scraper with caching and an SSRF guard
│   │   ├── notifications.py # Reminder engine and Web Push delivery
│   │   └── excel_export.py  # Formatted .xlsx report
│   ├── utils/timeutil.py    # Timezone helpers (stored as UTC, shown in local time)
│   ├── templates/           # Jinja2 templates
│   └── static/              # CSS, JS, service worker, manifest, icons
├── scripts/seed_demo.py     # Demo household generator
├── tests/                   # pytest suite
├── config.py                # Settings loaded from environment variables and .env
└── run.py                   # Development server entry point
```

## Security

- CSRF protection on every form and AJAX request
- Rate limits on login, sign-up, MedEx lookups and the cron endpoint
- Salted password hashing, plus a password check and a typed confirmation before an account is deleted
- Every query is scoped to the logged-in user, so one account can't read another household's records
- An SSRF guard: the server only fetches `medex.com.bd` URLs, even though the URL comes from the client
- Open-redirect protection on the login `?next=` parameter
- The cron token is compared in constant time
- User-entered and scraped text is HTML-escaped before it is inserted into the DOM

The app is meant to be self-hosted by a single household. The cron token is shared across the whole instance.

## Disclaimer

MediTrack is a personal organisation tool. It is not a medical device and does not give medical advice. Always follow your doctor's or pharmacist's instructions. MedEx data is scraped from a third-party site, so it may be incomplete, and the autofill may stop working if the site's layout changes.

## License

Released under the [MIT License](LICENSE).
