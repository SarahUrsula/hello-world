# SANParks Otter Trail – Availability Tracker

Watches the SANParks booking portal for Otter Trail cancellations / new slots
and notifies you the moment something opens up.

> **Why local instead of cloud?**  SANParks sits behind Cloudflare bot
> protection. GitHub Actions / datacenter IPs get hard-blocked. Running on
> your own machine with a real Chrome profile gets through transparently.

## How it works

1. Opens your installed Google Chrome via Playwright with a persistent
   profile in `browser_profile/` — once Cloudflare trusts the profile,
   subsequent runs sail through, even headless.
2. Navigates `https://www.sanparks.org/reservations/overnight-activity-details/396/1/<date>`
   for one date in each upcoming month, scraping the rendered Angular
   calendar for days where `available-sub > 0`.
3. Diffs against `state.json` and notifies if any **new** slots have
   appeared since the last run.

## One-time setup

```powershell
# 1. Install deps
pip install -r requirements.txt
python -m playwright install chromium

# 2. First run — visible browser, you may need to click "Verify you are human" once.
$env:HEADLESS="false"; python checker.py

# 3. Configure notifications (optional but recommended)
copy .env.example .env
notepad .env
```

## Schedule it (Windows Task Scheduler)

From an **elevated** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File schedule_task.ps1
```

This registers a task called **"Otter Trail Checker"** with a targeted daily
schedule — dense in the morning window (when SANParks typically releases new
slots) and a couple of afternoon checks:

| Time | Reason |
|------|--------|
| 08:00, 08:15, 08:30, 08:45, 09:00, 09:15 | Morning release window |
| 13:00, 17:00 | Afternoon spot-checks |

Logs go to `checker.log`.

To remove later: `Unregister-ScheduledTask -TaskName "Otter Trail Checker" -Confirm:$false`

## Notification options (`.env`)

| Variable | What it does |
|---|---|
| `EMAIL_ENABLED=true` + `SMTP_*` / `EMAIL_*` | Email via SMTP (Gmail App Password recommended) |
| `TELEGRAM_ENABLED=true` + `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram bot DM |
| (always on, Windows only) | Native Windows toast notification |

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `MONTHS_TO_CHECK` | `11` | How many months ahead to scan |
| `HEADLESS` | `true` | `false` shows the Chrome window |
| `STATE_FILE` | `state.json` | Where known availability is persisted |
| `PROFILE_DIR` | `browser_profile` | Chrome user-data-dir (cookies live here) |
| `STATUS_NOTIFY` | `false` | `true` sends a Telegram status on every run (testing mode); `false` only notifies when slots change |

## Troubleshooting

**Cloudflare keeps blocking you** — run once with `HEADLESS=false` and
solve the "Verify you are human" challenge by hand. Once the cookies
land in `browser_profile/`, headless runs work for hours/days.

**"Calendar didn't render"** — the SANParks Angular page sometimes takes
a few seconds. The script already waits 30s; if it still fails, your
network is slow or the site is down.

**Test what's on the page** — set `HEADLESS=false` and watch the run.

## Notes

- Otter Trail ID in SANParks system = **396**.
- Bookings open ~11 months in advance.
- Trail is 5 nights / 6 days; the *start date* is what you book.
- Max group size is 12 — cancellations DO happen, especially close to the date.
