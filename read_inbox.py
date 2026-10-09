"""
read_inbox.py - reads emails from Gmail over IMAP (read-only).
Used by agent.py. Can also be run on its own for a one-off batch: it reads the
inbox WITHOUT marking emails as read, asks the AI to sort each new email, and
logs the result to the Google Sheet (no Telegram, nothing sent).
Emails it has already handled are remembered in processed.json and skipped.
"""
import email
import imaplib
import json
import os
import re
import time
import webbrowser
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv

from ai import classify_email
from sheets import log_to_sheet

load_dotenv()
ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
HOW_MANY = 10  # how many of the newest emails to check each run
PROCESSED_FILE = Path(__file__).with_name("processed.json")


def decode(value) -> str:
    """Email headers can be encoded (e.g. emojis or accents). This makes them readable."""
    return str(make_header(decode_header(value or "")))


def get_body(msg) -> str:
    """Pull the plain-text body out of an email (falls back to HTML with the tags removed)."""
    plain, html = None, None
    for part in msg.walk():
        if part.is_multipart() or "attachment" in str(part.get("Content-Disposition", "")):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and plain is None:
            plain = text
        elif part.get_content_type() == "text/html" and html is None:
            html = text
    if plain is None and html:
        plain = re.sub(r"<[^>]+>", " ", html)  # remove HTML tags
    body = re.sub(r"\s+", " ", plain or "").strip()
    return body[:3000]  # long emails are cut short to keep the AI fast


def format_date(raw) -> str:
    try:
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return raw or ""


def fetch_latest_emails(how_many: int) -> list[dict]:
    """Log in to Gmail over IMAP and return the newest emails as simple dictionaries."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(ADDRESS, APP_PASSWORD)
    mail.select("INBOX", readonly=True)  # readonly = we never change anything

    _, data = mail.search(None, "ALL")
    ids = data[0].split()[-how_many:]  # the last N are the newest

    emails = []
    for email_id in reversed(ids):  # newest first
        _, msg_data = mail.fetch(email_id, "(BODY.PEEK[])")  # PEEK = don't mark as read
        msg = email.message_from_bytes(msg_data[0][1])
        emails.append({
            "message_id": (msg["Message-ID"] or f"no-id-{email_id.decode()}").strip(),
            "date": format_date(msg["Date"]),
            "sender": parseaddr(decode(msg["From"]))[1],
            "subject": decode(msg["Subject"]),
            "body": get_body(msg),
        })
    mail.logout()
    return emails


def load_processed() -> set:
    if PROCESSED_FILE.exists():
        return set(json.loads(PROCESSED_FILE.read_text(encoding="utf-8")))
    return set()


def save_processed(ids: set) -> None:
    PROCESSED_FILE.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")


def main():
    if not ADDRESS or not APP_PASSWORD:
        print("Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to your .env file first.")
        return

    print(f"Connecting to {ADDRESS}...")
    try:
        emails = fetch_latest_emails(HOW_MANY)
    except imaplib.IMAP4.error as e:
        print(f"\nGmail login failed: {e}")
        print("Check the address and app password in .env, and that 2-Step Verification is on.")
        return

    processed = load_processed()
    new_emails = [e for e in emails if e["message_id"] not in processed]
    print(f"Found {len(emails)} emails, {len(new_emails)} new.\n")
    if not new_emails:
        print("Nothing new to sort. Send another test email and run again.")
        return

    for i, item in enumerate(new_emails, start=1):
        result = classify_email(item["sender"], item["subject"], item["body"])
        print("=" * 60)
        print(f"{i}. From:    {item['sender']}")
        print(f"   Subject: {item['subject']}")
        print(f"   -> {result['category'].upper()} | urgency: {result['urgency']}")
        print(f"   Summary: {result['summary']}")
        if result["draft_reply"]:
            print(f"   Draft reply:\n   {result['draft_reply']}")

        try:
            log_to_sheet(item, result)
            print("   Logged to Google Sheet")
        except Exception as e:
            print(f"   Could not log to the sheet: {e}")
            print("   Stopping here so nothing gets skipped. Fix the problem and run again.")
            break

        processed.add(item["message_id"])
        save_processed(processed)  # saved after each email, so a crash loses nothing
        time.sleep(2)  # small pause so we stay inside the free AI limits

    print("=" * 60)
    print("\nDone. Nothing was sent and no emails were marked as read.")

    # Open the Google Sheet so you can see the new rows
    sheet_url = os.getenv("SHEET_URL", "").strip()
    if sheet_url:
        print("Opening your Google Sheet...")
        webbrowser.open(sheet_url)


if __name__ == "__main__":
    main()
