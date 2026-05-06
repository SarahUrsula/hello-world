# SANParks Otter Trail – Availability Tracker

Watches the SANParks booking portal for Otter Trail cancellations / new slots
and sends you a notification the moment something opens up.

## How it works

1. Launches a headless Chromium browser (via Playwright) to load the
   SANParks booking page for the Otter Trail.
2. Navigates the availability calendar across the next **11 months**
   (configurable via `MONTHS_TO_CHECK` in `.env`).
3. Compares what it found against `state.json` from the previous run.
4. If any **new** available dates appear it fires a notification via:
   - Desktop pop-up (`notify-send`)
   - Email (optional SMTP / Gmail App Password)
   - Telegram bot (optional)
5. Saves the latest availability to `state.json` so the next run only
   alerts on genuinely new changes.

## Setup

```bash
bash setup.sh        # installs deps + Playwright Chromium browser
```

Then edit `.env` (copied from `.env.example`) with your notification details.

## Running

```bash
# One-off check
python checker.py

# Watch the log
tail -f checker.log
```

## Scheduling (cron – every 10 minutes)

```bash
crontab -e
```

Add:
```
*/10 * * * * cd /full/path/to/this/directory && python checker.py >> checker.log 2>&1
```

For more frequent checks (every 5 minutes):
```
*/5 * * * * cd /full/path/to/this/directory && python checker.py >> checker.log 2>&1
```

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `MONTHS_TO_CHECK` | `11` | How many months ahead to scan |
| `HEADLESS` | `true` | `false` shows the browser window (good for debugging) |
| `EMAIL_ENABLED` | `false` | Set to `true` + fill SMTP fields to get emails |
| `TELEGRAM_ENABLED` | `false` | Set to `true` + fill token/chat_id for Telegram |
| `STATE_FILE` | `state.json` | Where availability state is persisted |

## Troubleshooting

**"No availability data was scraped"** – SANParks may have updated their
booking portal HTML. Run with `HEADLESS=false` in `.env` to watch what the
browser does, then update the selectors in `checker.py` (`fetch_availability`).

**Blocked / CAPTCHA** – Add a longer `wait_for_timeout` delay or run less
frequently. The script already uses a realistic browser user-agent.

## Notes

- SANParks opens Otter Trail bookings 11 months in advance.
- The trail runs 5 nights / 6 days; you book the **start date**.
- Max group size is 12 people; groups sometimes cancel close to the date.
