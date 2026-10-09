"""
sheets.py - talks to your Google Sheet and Google Calendar through the Apps Script webhook.
"""
import json
import os
import urllib.request

from dotenv import load_dotenv

load_dotenv()
WEBHOOK_URL = os.getenv("SHEETS_WEBHOOK_URL", "").strip()
SECRET = os.getenv("SHEETS_SECRET", "").strip()


def _post(payload: dict) -> str:
    if not WEBHOOK_URL or not SECRET:
        raise RuntimeError("Add SHEETS_WEBHOOK_URL and SHEETS_SECRET to your .env file.")
    payload = {"secret": SECRET, **payload}
    request = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace").strip()


def log_to_sheet(item: dict, result: dict) -> None:
    """Add one row to the sheet. Raises an error if the sheet doesn't say 'ok'."""
    meeting = ""
    if result.get("meeting_start"):
        meeting = f"{result['meeting_start']} ({result['meeting_minutes']} min)"
    reply = _post({
        "message_id": item["message_id"],
        "date": item["date"],
        "sender": item["sender"],
        "subject": item["subject"],
        "category": result["category"],
        "urgency": result["urgency"],
        "summary": result["summary"],
        "draft_reply": result["draft_reply"],
        "meeting": meeting,
    })
    if reply != "ok":
        raise RuntimeError(f"The sheet didn't accept the row. It replied: {reply[:200]}")


def update_sheet_status(message_id: str, status: str) -> bool:
    """Change the Status column for an email already in the sheet. Returns True if it worked."""
    try:
        return _post({"action": "update_status", "message_id": message_id, "status": status}) == "ok"
    except Exception as e:
        print(f"   Could not update the sheet status: {e}")
        return False


def check_calendar(start: str, minutes: int) -> str:
    """Return 'free', 'busy' or 'unknown' for that time slot in your Google Calendar."""
    try:
        answer = _post({"action": "check_free", "start": start, "minutes": minutes})
        return answer if answer in ("free", "busy") else "unknown"
    except Exception as e:
        print(f"   Could not check the calendar: {e}")
        return "unknown"


def create_calendar_event(start: str, minutes: int, title: str, description: str,
                          guest: str | None = None) -> None:
    """Create the meeting in your Google Calendar. Raises an error if it fails."""
    answer = _post({"action": "create_event", "start": start, "minutes": minutes,
                    "title": title, "description": description, "guest": guest or ""})
    if answer != "ok":
        raise RuntimeError(f"The calendar didn't accept the event. It replied: {answer[:200]}")
