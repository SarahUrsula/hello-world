"""
SANParks Otter Trail availability tracker (LOCAL version).

The SANParks site sits behind Cloudflare bot protection, so this is built
to run *locally* on your Windows machine with a persistent Chrome profile —
you solve Cloudflare once and the cookies stick.

First run (interactive):
    set HEADLESS=false&& python checker.py
    -> a Chrome window opens; if you see a Cloudflare "Verify you are human"
       prompt, click it. Once the booking page loads, the script takes over.

Subsequent runs:
    python checker.py     (headless once profile is trusted)

Schedule via Windows Task Scheduler — see schedule_task.ps1.
"""

import asyncio
import json
import os
import smtplib
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

MONTHS_TO_CHECK  = int(os.getenv("MONTHS_TO_CHECK") or "11")
HEADLESS         = os.getenv("HEADLESS", "true").lower() == "true"
STATE_FILE       = Path(os.getenv("STATE_FILE", "state.json"))
PROFILE_DIR      = Path(os.getenv("PROFILE_DIR", "browser_profile")).absolute()

EMAIL_ENABLED    = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_FROM       = os.getenv("EMAIL_FROM", "")
EMAIL_TO         = os.getenv("EMAIL_TO", "")
SMTP_HOST        = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT        = int(os.getenv("SMTP_PORT") or "587")
SMTP_USER        = os.getenv("SMTP_USER", "")
SMTP_PASS        = os.getenv("SMTP_PASS", "")

TELEGRAM_ENABLED  = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "")

# Otter Trail booking page. ID 396 = Otter Trail; the trailing date drives
# which month's calendar the page renders.
TRAIL_URL_TEMPLATE = (
    "https://www.sanparks.org/reservations/overnight-activity-details/396/1/{date}"
)

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

def notify_windows_toast(title: str, body: str) -> None:
    """Fire a Windows 10/11 toast notification via PowerShell."""
    if os.name != "nt":
        return
    try:
        import subprocess
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,"
            "ContentType=WindowsRuntime] | Out-Null;"
            "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,"
            "ContentType=WindowsRuntime] | Out-Null;"
            "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            f'$t.GetElementsByTagName("text")[0].InnerText="{title}";'
            f'$t.GetElementsByTagName("text")[1].InnerText="{body[:200]}";'
            "$n=[Windows.UI.Notifications.ToastNotification]::new($t);"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier"
            "('Otter Trail Tracker').Show($n)"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=10)
    except Exception:
        pass

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
        f"?chat_id={TELEGRAM_CHAT_ID}&text={urllib.parse.quote(text)}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                print(f"[notify] Telegram HTTP {resp.status}")
            else:
                print("[notify] Telegram message sent")
    except Exception as exc:
        print(f"[notify] Telegram failed: {exc}")

def send_notifications(new_slots: dict[str, list[str]]) -> None:
    lines = ["Otter Trail slots just opened on SANParks!\n"]
    for month, dates in sorted(new_slots.items()):
        lines.append(f"  {month}:")
        for d in sorted(dates):
            lines.append(f"    - {d}")
    lines.append("\nBook now: https://www.sanparks.org/reservations")
    message = "\n".join(lines)

    print(message)
    notify_windows_toast("Otter Trail Available!", "\n".join(lines[1:5]))
    notify_email("Otter Trail slots available!", message)
    notify_telegram(message)

# ── Cloudflare detection ──────────────────────────────────────────────────────

async def is_cloudflare_challenge(page) -> bool:
    title = (await page.title()).lower()
    return "just a moment" in title or "checking your browser" in title

async def wait_through_cloudflare(page, timeout_ms: int = 45_000) -> bool:
    print("[scraper] Cloudflare challenge detected -- waiting for it to clear ...")
    try:
        await page.wait_for_function(
            "() => !document.title.toLowerCase().includes('just a moment') "
            "&& !document.title.toLowerCase().includes('checking your browser')",
            timeout=timeout_ms,
        )
        return True
    except PWTimeout:
        return False

# ── Browser scraper ────────────────────────────────────────────────────────────

async def fetch_month(page, target: date) -> list[str]:
    url = TRAIL_URL_TEMPLATE.format(date=target.strftime("%Y-%m-%d"))
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

    if await is_cloudflare_challenge(page):
        if not await wait_through_cloudflare(page):
            print("[scraper] Cloudflare did not clear -- run with HEADLESS=false to solve it manually")
            return []

    # Wait for the Angular calendar to fully render
    try:
        await page.wait_for_selector(".schedular-table .day", timeout=30_000)
    except PWTimeout:
        print(f"[scraper] Calendar didn't render for {target:%B %Y}")
        return []

    # Verify we're looking at the expected month
    try:
        heading = (await page.locator(".calendar-heading strong").first.inner_text()).strip()
    except Exception:
        heading = "?"
    expected = target.strftime("%B %Y")
    if heading != expected:
        print(f"  [warn] calendar shows {heading!r}, expected {expected!r}")

    # A day cell looks like:
    #   <div class="day ... [greyedout] ...">
    #     <div class="date">15</div>
    #     <div class="available-main">
    #       <div class="available-sub">2</div>   <-- units available
    #     </div>
    #   </div>
    # Available = available-sub text is a positive integer.
    available = await page.evaluate("""
        () => {
            const out = [];
            document.querySelectorAll('.schedular-table .day').forEach(d => {
                const dayText = d.querySelector('.date')?.innerText.trim();
                const availText = d.querySelector('.available-sub')?.innerText.trim();
                if (!dayText) return;
                const n = parseInt(availText || '0', 10);
                if (!Number.isNaN(n) && n > 0) out.push({ day: dayText, units: n });
            });
            return out;
        }
    """)
    # Format as "DD (N units)" so notifications include the unit count
    return [f"{d['day']} ({d['units']} units)" for d in available]


async def run_check() -> None:
    previous = load_state()
    current: dict[str, list[str]] = {}

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[tracker] Using browser profile at: {PROFILE_DIR}")

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",   # use installed Google Chrome — better at passing Cloudflare
            headless=HEADLESS,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            today = date.today()
            for month_offset in range(MONTHS_TO_CHECK):
                target = today.replace(day=1) + relativedelta(months=month_offset)
                lookup = target if target > today else today
                month_key = target.strftime("%Y-%m")
                print(f"[scraper] Checking {target:%B %Y} ...")
                try:
                    days = await fetch_month(page, lookup)
                except Exception as exc:
                    print(f"  ! error: {exc}")
                    continue
                if days:
                    current[month_key] = days
                    print(f"  -> {len(days)} available: {days[:10]}")
                else:
                    print("  -> none available")
        finally:
            await context.close()

    new_slots: dict[str, list[str]] = {}
    for month, days in current.items():
        prev = set(previous.get(month, []))
        fresh = [d for d in days if d not in prev]
        if fresh:
            new_slots[month] = fresh

    if new_slots:
        print(f"\n[tracker] NEW slots: {new_slots}")
        send_notifications(new_slots)
    else:
        print(f"\n[tracker] No new slots. Scanned {len(current)} month(s) with availability.")
        if not current:
            print("[tracker] WARNING: zero months returned data. Selectors may need tuning, "
                  "or Cloudflare blocked us -- try HEADLESS=false once.")

    save_state({**previous, **current})
    print(f"[tracker] State saved to {STATE_FILE.absolute()}")


if __name__ == "__main__":
    print(f"[tracker] SANParks Otter Trail checker - {datetime.now():%Y-%m-%d %H:%M:%S}")
    asyncio.run(run_check())
