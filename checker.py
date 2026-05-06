"""
SANParks Otter Trail availability tracker.

Checks the SANParks booking portal for Otter Trail openings across all
upcoming months and sends a notification whenever new slots appear.

Run manually:
    python checker.py

Schedule with cron (every 10 minutes):
    */10 * * * * cd /path/to/this/dir && python checker.py >> checker.log 2>&1
"""

import asyncio
import json
import os
import smtplib
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

MONTHS_TO_CHECK  = int(os.getenv("MONTHS_TO_CHECK", "11"))
HEADLESS         = os.getenv("HEADLESS", "true").lower() == "true"
STATE_FILE       = Path(os.getenv("STATE_FILE", "state.json"))

EMAIL_ENABLED    = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_FROM       = os.getenv("EMAIL_FROM", "")
EMAIL_TO         = os.getenv("EMAIL_TO", "")
SMTP_HOST        = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT        = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER        = os.getenv("SMTP_USER", "")
SMTP_PASS        = os.getenv("SMTP_PASS", "")

TELEGRAM_ENABLED  = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "")

# SANParks booking portal – Otter Trail (Tsitsikamma / Garden Route NP)
# The trail ID in their system is 59982.  If the portal ever changes, update
# BOOKING_URL to the new trail landing page.
BOOKING_URL = (
    "https://www.sanparks.org/tourism/conservation/reserves/garden_route/otter.php"
)
TRAILS_URL  = "https://www.sanparks.org/reservations/"

# ── State helpers ──────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── Notification helpers ───────────────────────────────────────────────────────

def notify_desktop(title: str, body: str) -> None:
    """Fire a desktop notification (Linux notify-send)."""
    try:
        subprocess.run(["notify-send", "-u", "critical", title, body], check=False)
    except FileNotFoundError:
        pass  # notify-send not available

def notify_email(subject: str, body: str) -> None:
    if not EMAIL_ENABLED:
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"[notify] Email sent to {EMAIL_TO}")
    except Exception as exc:
        print(f"[notify] Email failed: {exc}")

def notify_telegram(text: str) -> None:
    if not TELEGRAM_ENABLED:
        return
    url = (
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        f"?chat_id={TELEGRAM_CHAT_ID}&text={urllib.parse.quote(text)}&parse_mode=HTML"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            if resp.status != 200:
                print(f"[notify] Telegram HTTP {resp.status}")
            else:
                print("[notify] Telegram message sent")
    except Exception as exc:
        print(f"[notify] Telegram failed: {exc}")

def send_notifications(new_slots: dict[str, list[str]]) -> None:
    """new_slots: { 'YYYY-MM': ['DD Mon YYYY', ...] }"""
    lines = ["🏔  Otter Trail slots just opened on SANParks!\n"]
    for month, dates in sorted(new_slots.items()):
        lines.append(f"  {month}:")
        for d in sorted(dates):
            lines.append(f"    • {d}")
    lines.append(f"\nBook now: {TRAILS_URL}")
    message = "\n".join(lines)

    print(message)
    notify_desktop("Otter Trail Available!", "\n".join(lines[:6]))
    notify_email("🏔 Otter Trail slots available!", message)
    notify_telegram(message.replace("🏔", "").strip())

# ── Browser scraper ────────────────────────────────────────────────────────────

async def fetch_availability(page) -> dict[str, list[str]]:
    """
    Navigate the SANParks booking portal to find Otter Trail availability.
    Returns a dict of { 'YYYY-MM': [list of available date strings] }.
    """
    availability: dict[str, list[str]] = {}

    print(f"[scraper] Opening SANParks booking portal …")
    await page.goto(BOOKING_URL, wait_until="domcontentloaded", timeout=60_000)

    # Accept any cookie/popup banners
    for selector in ["button:has-text('Accept')", "button:has-text('I Agree')",
                     "#onetrust-accept-btn-handler", ".cc-accept"]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                break
        except PWTimeout:
            pass

    # Look for the "Book Now" / "Book Trail" CTA on the Otter Trail page
    booked = False
    for selector in [
        "a:has-text('Book Now')",
        "a:has-text('Book Trail')",
        "a:has-text('Book')",
        "input[value*='Book']",
        "button:has-text('Book')",
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=4_000):
                await btn.click()
                booked = True
                break
        except PWTimeout:
            pass

    if not booked:
        # Fall back: navigate directly to the reservations portal and search
        print("[scraper] Could not find Book button on trail page – trying reservations portal")
        await page.goto(TRAILS_URL, wait_until="domcontentloaded", timeout=60_000)

        # Try searching for Otter Trail in their search box
        for sel in ["input[placeholder*='Search']", "input[name*='search']",
                    "input[type='search']", "#search"]:
            try:
                box = page.locator(sel).first
                if await box.is_visible(timeout=3_000):
                    await box.fill("Otter Trail")
                    await box.press("Enter")
                    break
            except PWTimeout:
                pass

        # Click first Otter Trail result
        try:
            result = page.locator("a:has-text('Otter Trail')").first
            await result.click(timeout=8_000)
        except PWTimeout:
            print("[scraper] Could not navigate to Otter Trail page – selector may have changed")
            return availability

    # Wait for a calendar/date-picker to appear
    await page.wait_for_timeout(3_000)
    print("[scraper] Looking for availability calendar …")

    # ── Month iteration ──────────────────────────────────────────────────────
    today = date.today()
    for month_offset in range(MONTHS_TO_CHECK):
        target = today + relativedelta(months=month_offset)
        month_key = target.strftime("%Y-%m")
        print(f"[scraper] Checking {target.strftime('%B %Y')} …")

        # Navigate forward if not on the first month
        if month_offset > 0:
            for nav_sel in [
                "button[aria-label*='Next']",
                "button[aria-label*='next']",
                "button:has-text('>')",
                ".calendar-next",
                ".fc-next-button",
                "[data-action='next']",
            ]:
                try:
                    btn = page.locator(nav_sel).first
                    if await btn.is_visible(timeout=3_000):
                        await btn.click()
                        await page.wait_for_timeout(1_500)
                        break
                except PWTimeout:
                    pass

        # Extract available (enabled, not greyed-out) dates from calendar
        available_in_month: list[str] = []

        # SANParks typically renders available days as <td> or <button> with
        # an "available" class and no "disabled" attribute.
        for day_sel in [
            "td.available:not(.disabled)",
            "td[class*='available']:not([class*='disabled'])",
            "button[class*='available']:not([disabled])",
            ".day.available",
            "[aria-disabled='false']:not(.blocked)",
            "td:not(.disabled):not(.blocked):not(.past) a",
        ]:
            day_els = await page.locator(day_sel).all()
            if day_els:
                for el in day_els:
                    label = await el.get_attribute("aria-label") or await el.inner_text()
                    label = label.strip()
                    if label:
                        available_in_month.append(label)
                break  # found the right selector

        if available_in_month:
            availability[month_key] = available_in_month
            print(f"  → {len(available_in_month)} available date(s): {available_in_month[:5]}")
        else:
            print(f"  → No available dates (or calendar not loaded)")

    return availability


async def run_check() -> None:
    previous = load_state()
    current: dict[str, list[str]] = {}

    async with async_playwright() as pw:
        # --no-sandbox is required in GitHub Actions / most CI environments
        ci_args = ["--no-sandbox", "--disable-setuid-sandbox"] if os.getenv("CI") else []
        browser = await pw.chromium.launch(headless=HEADLESS, args=ci_args)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            current = await fetch_availability(page)
        except Exception as exc:
            print(f"[error] Scrape failed: {exc}")
        finally:
            await browser.close()

    # ── Diff: find newly available slots ──────────────────────────────────────
    new_slots: dict[str, list[str]] = {}
    for month, dates in current.items():
        prev_dates = set(previous.get(month, []))
        fresh = [d for d in dates if d not in prev_dates]
        if fresh:
            new_slots[month] = fresh

    if new_slots:
        print(f"\n[tracker] NEW slots found: {new_slots}")
        send_notifications(new_slots)
    else:
        print(f"\n[tracker] No new slots. Checked {len(current)} month(s).")
        if not current:
            print("[tracker] Warning: no availability data was scraped – selectors may need updating.")

    # Merge and save (keep months even when no availability, to track drops too)
    merged = {**previous, **current}
    save_state(merged)
    print(f"[tracker] State saved to {STATE_FILE}")


if __name__ == "__main__":
    print(f"[tracker] SANParks Otter Trail checker – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    asyncio.run(run_check())
