"""
agent.py - the AI Inbox Agent, with human approval for every action.

While running, it:
  1. checks the inbox every couple of minutes for new emails
  2. sorts each one with AI and logs it to the Google Sheet
  3. for booking requests, works out the meeting time and checks Google Calendar
  4. sends the draft reply to Telegram with Approve / Reject buttons
  5. ONLY when approved: sends the reply and books the meeting,
     and only to addresses on the safety list (SEND_ONLY_TO)

Start it:  venv\\Scripts\\python agent.py      Stop it:  press Ctrl + C
"""
import hashlib
import json
import os
import smtplib
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

from ai import classify_email
from read_inbox import ADDRESS, APP_PASSWORD, fetch_latest_emails, load_processed, save_processed
from sheets import check_calendar, create_calendar_event, log_to_sheet, update_sheet_status

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
# Safety list: replies can ONLY be sent to these addresses (comma separated)
SEND_ONLY_TO = {a.strip().lower() for a in os.getenv("SEND_ONLY_TO", "").split(",") if a.strip()}

CHECK_EVERY = 120  # seconds between inbox checks
PENDING_FILE = Path(__file__).with_name("pending.json")


# ---------- Telegram ----------

def telegram(method: str, params: dict) -> dict:
    """Call a Telegram Bot API method and return its result. Retries if the connection is slow."""
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=json.dumps(params).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == 3:
                raise
            print(f"   Telegram connection slow ({e}), retrying...")
            time.sleep(3)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data}")
    return data["result"]


def nice_time(start: str) -> str:
    """'2026-10-13 14:00' -> 'Tue 13 Oct, 14:00'"""
    return datetime.strptime(start, "%Y-%m-%d %H:%M").strftime("%a %d %b, %H:%M")


def send_for_approval(key: str, entry: dict) -> None:
    item, result = entry["item"], entry["result"]
    text = (
        f"NEW EMAIL ({result['category'].upper()}, urgency: {result['urgency']})\n"
        f"From: {item['sender']}\n"
        f"Subject: {item['subject']}\n\n"
        f"Summary: {result['summary']}\n\n"
    )
    if result.get("meeting_start"):
        calendar_note = {
            "free": "your calendar is FREE",
            "busy": "WARNING: you already have something booked then",
        }.get(entry.get("calendar"), "couldn't check your calendar")
        text += (f"MEETING: {nice_time(result['meeting_start'])} "
                 f"({result['meeting_minutes']} min), {calendar_note}\n\n")
        buttons = [
            [{"text": "Approve + book", "callback_data": f"book:{key}"},
             {"text": "Approve, don't book", "callback_data": f"approve:{key}"}],
            [{"text": "Reject", "callback_data": f"reject:{key}"}],
        ]
    else:
        buttons = [[
            {"text": "Approve and send", "callback_data": f"approve:{key}"},
            {"text": "Reject", "callback_data": f"reject:{key}"},
        ]]
    text += f"DRAFT REPLY:\n{result['draft_reply']}"
    telegram("sendMessage", {"chat_id": CHAT_ID, "text": text,
                             "reply_markup": {"inline_keyboard": buttons}})


# ---------- Pending approvals (saved to disk so a restart loses nothing) ----------

def load_pending() -> dict:
    if PENDING_FILE.exists():
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    return {}


def save_pending(pending: dict) -> None:
    PENDING_FILE.write_text(json.dumps(pending, indent=2), encoding="utf-8")


# ---------- Sending the email reply ----------

def send_reply(item: dict, reply_text: str) -> None:
    msg = EmailMessage()
    msg["From"] = ADDRESS
    msg["To"] = item["sender"]
    subject = item["subject"] or ""
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg["In-Reply-To"] = item["message_id"]  # these two lines make it appear in the same thread
    msg["References"] = item["message_id"]
    msg.set_content(reply_text)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(ADDRESS, APP_PASSWORD)
        smtp.send_message(msg)


# ---------- The main jobs ----------

def check_inbox(processed: set, pending: dict) -> None:
    emails = fetch_latest_emails(10)
    new_emails = [e for e in emails if e["message_id"] not in processed]
    print(f"[{time.strftime('%H:%M')}] Checked inbox: {len(new_emails)} new email(s).")
    for item in new_emails:
        print(f"New email from {item['sender']}: {item['subject']}")
        try:
            result = classify_email(item["sender"], item["subject"], item["body"])
            log_to_sheet(item, result)
        except Exception as e:
            print(f"   Skipped for now (will retry next check): {e}")
            continue

        if result["draft_reply"]:
            key = hashlib.sha1(item["message_id"].encode()).hexdigest()[:12]
            item.pop("body", None)  # no need to keep the full email
            entry = {"item": item, "result": result, "notified": False}
            if result.get("meeting_start"):
                entry["calendar"] = check_calendar(result["meeting_start"], result["meeting_minutes"])
                print(f"   Meeting requested: {nice_time(result['meeting_start'])} "
                      f"(calendar: {entry['calendar']})")
            pending[key] = entry
            save_pending(pending)
            print(f"   {result['category']}: waiting for your approval")
        else:
            print(f"   {result['category']}: no reply needed")

        # Mark as done straight away, so a Telegram hiccup never logs it twice
        processed.add(item["message_id"])
        save_processed(processed)
        time.sleep(2)


def notify_pending(pending: dict) -> None:
    """Send any approvals that haven't reached Telegram yet (e.g. after a connection drop)."""
    for key, entry in pending.items():
        if entry.get("notified", True):
            continue
        try:
            send_for_approval(key, entry)
            entry["notified"] = True
            save_pending(pending)
            print(f"   Sent to Telegram: {entry['item']['subject']}")
        except Exception as e:
            print(f"   Telegram not reachable yet ({e}), will retry shortly.")
            return


def handle_button(callback: dict, pending: dict) -> None:
    # Only you can approve: ignore button presses from any other chat
    if str(callback["message"]["chat"]["id"]) != CHAT_ID:
        return
    action, key = callback["data"].split(":", 1)
    original = callback["message"].get("text", "")

    entry = pending.pop(key, None)
    if entry is None:
        outcome = "Already handled."
    elif action == "reject":
        update_sheet_status(entry["item"]["message_id"], "Rejected")
        outcome = "REJECTED. Nothing was sent."
    else:
        item, result = entry["item"], entry["result"]
        on_safety_list = item["sender"].lower() in SEND_ONLY_TO
        notes, statuses = [], []

        # 1. Book the meeting (only if you tapped "Approve + book")
        if action == "book" and result.get("meeting_start") and not entry.get("booked"):
            try:
                create_calendar_event(
                    result["meeting_start"], result["meeting_minutes"],
                    title=f"Call with {item['sender']}",
                    description=f"{item['subject']}\n\n{result['summary']}",
                    guest=item["sender"] if on_safety_list else None,  # invites follow the safety list too
                )
                entry["booked"] = True
                notes.append(f"BOOKED {nice_time(result['meeting_start'])} in your calendar"
                             + (" and invited them." if on_safety_list else " (no invite sent)."))
                statuses.append("Booked")
            except Exception as e:
                notes.append(f"Booking failed: {e}")

        # 2. Send the reply (only to addresses on the safety list)
        if not on_safety_list:
            notes.append(f"Reply BLOCKED: {item['sender']} is not on your safety list.")
            statuses.append("Reply blocked by safety list")
        else:
            try:
                send_reply(item, result["draft_reply"])
                notes.append("Reply SENT.")
                statuses.append("Sent")
            except Exception as e:
                pending[key] = entry  # keep it so you can try again
                notes.append(f"Sending failed: {e}")

        if statuses:
            update_sheet_status(item["message_id"], " + ".join(statuses))
        outcome = " ".join(notes)

    save_pending(pending)
    print(f"Button pressed: {outcome}")
    telegram("answerCallbackQuery", {"callback_query_id": callback["id"]})
    telegram("editMessageText", {
        "chat_id": CHAT_ID,
        "message_id": callback["message"]["message_id"],
        "text": f"{original}\n\n>>> {outcome}",
    })


def main():
    if not BOT_TOKEN:
        print("Add TELEGRAM_BOT_TOKEN to your .env file first.")
        return
    if not CHAT_ID:
        print("TELEGRAM_CHAT_ID is not set yet.")
        print("Send any message to your bot on Telegram now and your chat ID will appear here...")

    processed, pending = load_processed(), load_pending()
    offset, last_check = None, 0.0
    if CHAT_ID:
        try:
            telegram("sendMessage", {"chat_id": CHAT_ID, "text": "Inbox agent started. Watching for new emails."})
            print("Telegram works: start-up message sent.")
        except Exception as e:
            print(f"Could not message you on Telegram: {e}")
            print("Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env, and that you've pressed Start on your bot.")
            return
    print(f"Agent running. Checking the inbox every {CHECK_EVERY // 60} minutes. Press Ctrl + C to stop.\n")

    while True:
        try:
            if CHAT_ID and time.time() - last_check > CHECK_EVERY:
                last_check = time.time()
                check_inbox(processed, pending)
            notify_pending(pending)

            # Wait up to 20 seconds for button presses or messages from Telegram
            params = {"timeout": 20, "allowed_updates": ["message", "callback_query"]}
            if offset:
                params["offset"] = offset
            for update in telegram("getUpdates", params):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    handle_button(update["callback_query"], pending)
                elif "message" in update and not CHAT_ID:
                    chat_id = update["message"]["chat"]["id"]
                    print(f"\nYour chat ID is: {chat_id}")
                    print("Add  TELEGRAM_CHAT_ID=" + str(chat_id) + "  to .env, then restart the agent.")
                    return
        except KeyboardInterrupt:
            print("\nAgent stopped.")
            return
        except Exception as e:
            print(f"Problem: {e}. Trying again in 10 seconds...")
            time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent stopped.")
