"""
selftest.py - checks every part of the AI Inbox Agent in one go.
Double-click it (it can live in Downloads or in your inbox-agent folder).

It is SAFE: it does not send any emails, reply to anyone or create calendar events.
It only sends you one test message on Telegram.
"""
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def find_project() -> Path:
    here = Path(__file__).resolve().parent
    if (here / "agent.py").exists():
        return here
    home = Path.home()
    for desktop in (home / "OneDrive" / "Desktop", home / "Desktop"):
        if (desktop / "inbox-agent" / "agent.py").exists():
            return desktop / "inbox-agent"
    raise FileNotFoundError("Couldn't find your inbox-agent folder.")


FOLDER = find_project()

# Make sure we're running with the project's own Python (it has the packages installed)
VENV_PYTHON = FOLDER / "venv" / "Scripts" / "python.exe"
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    subprocess.run([str(VENV_PYTHON), str(Path(__file__).resolve())], cwd=FOLDER)
    sys.exit()

os.chdir(FOLDER)
sys.path.insert(0, str(FOLDER))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(FOLDER / ".env")
results = []


def check(name, test):
    print(f"\n--- {name} ---")
    try:
        detail = test()
        print(f"PASS  {detail or ''}")
        results.append((name, True))
    except Exception as e:
        print(f"FAIL  {e}")
        results.append((name, False))


# 1. Settings
def test_env():
    needed = ["GEMINI_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "SHEETS_WEBHOOK_URL",
              "SHEETS_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SEND_ONLY_TO"]
    missing = [k for k in needed if not os.getenv(k, "").strip()]
    if missing:
        raise RuntimeError("Missing from .env: " + ", ".join(missing))
    return "all 8 settings found (values not shown)"


# 2. AI, including working out a meeting time
def test_ai():
    from ai import classify_email
    result = classify_email(
        "priya@example.com", "Quick call?",
        "Hi, could we have a 30 minute call next Tuesday at 3pm about a new website? Thanks, Priya")
    print(f"      category={result['category']}, meeting={result.get('meeting_start')}, "
          f"minutes={result.get('meeting_minutes')}")
    print(f"      draft: {result['draft_reply'][:120]}")
    if result["category"] != "booking":
        raise RuntimeError(f"expected 'booking' but got '{result['category']}'")
    if not result.get("meeting_start") or not result["meeting_start"].endswith("15:00"):
        raise RuntimeError("expected a meeting next Tuesday at 15:00")
    return "AI sorted it as a booking and found the right time"


# 3. Gmail reading
def test_imap():
    import imaplib
    from read_inbox import ADDRESS, APP_PASSWORD
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(ADDRESS, APP_PASSWORD)
    _, data = mail.select("INBOX", readonly=True)
    mail.logout()
    return f"logged in, {int(data[0])} emails in the inbox"


# 4. Gmail sending (logs in only, sends nothing)
def test_smtp():
    import smtplib
    from read_inbox import ADDRESS, APP_PASSWORD
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(ADDRESS, APP_PASSWORD)
    return "login works (nothing sent)"


# 5. Google Sheet webhook + secret word
def test_sheet():
    from sheets import _post
    answer = _post({"action": "update_status", "message_id": "<selftest>", "status": "test"})
    if answer == "forbidden":
        raise RuntimeError("secret word in .env doesn't match the one in Apps Script")
    if answer != "not found":
        raise RuntimeError(f"unexpected answer (is the new version deployed?): {answer[:150]}")
    return "webhook reachable and secret word matches"


# 6. Google Calendar
def test_calendar():
    from sheets import _post
    slot = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") + " 03:00"
    answer = _post({"action": "check_free", "start": slot, "minutes": 30})
    if answer not in ("free", "busy"):
        raise RuntimeError("calendar check failed. Run testSetup in Apps Script to allow Calendar, "
                           f"then deploy a New version. Answer: {answer[:150]}")
    return f"calendar connected (tomorrow 03:00 is {answer})"


# 7. Telegram
def test_telegram():
    from agent import CHAT_ID, telegram
    bot = telegram("getMe", {})
    telegram("sendMessage", {"chat_id": CHAT_ID, "text": "Self-test: Telegram works."})
    return f"bot @{bot['username']} sent you a test message"


# 8. Safety list
def test_safety():
    from agent import SEND_ONLY_TO
    return "replies can only go to: " + ", ".join(sorted(SEND_ONLY_TO))


print(f"Testing the agent in: {FOLDER}")
for name, test in [("Settings (.env)", test_env), ("AI + meeting time", test_ai),
                   ("Gmail reading", test_imap), ("Gmail sending login", test_smtp),
                   ("Google Sheet", test_sheet), ("Google Calendar", test_calendar),
                   ("Telegram", test_telegram), ("Safety list", test_safety)]:
    check(name, test)

passed = sum(ok for _, ok in results)
print("\n" + "=" * 50)
for name, ok in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
print("=" * 50)
print(f"{passed} of {len(results)} checks passed.")
if passed == len(results):
    print("Everything works. Final check: send a booking email and tap 'Approve + book' on Telegram.")
else:
    print("See the FAIL lines above for what to fix.")
input("\nPress Enter to close...")
