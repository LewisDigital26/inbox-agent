"""
ai.py - the AI "brain" of the Inbox Agent.
Other files import classify_email() from here, so the AI code lives in one place.
"""
import json
import time
from datetime import datetime

from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv()
client = genai.Client()  # reads GEMINI_API_KEY from .env

# Lite model first (faster, less busy), full model as a backup
MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]

PROMPT = """You sort emails for a small business. Today is {today}.

Categories:
- enquiry: asking about NEW work, services, prices or availability
- complaint: a customer reporting that something has gone wrong: broken or faulty
  work, mistakes, poor service, or being charged wrongly. Use complaint even if it's
  polite or involves money (e.g. "I noticed some typos", "I was charged twice",
  "the contact form isn't working").
- invoice: routine money admin with nothing gone wrong: bills, payments made or failed,
  receipts, remittance, requests for an invoice. Use this even if it is automated.
- booking: wants to book, change or cancel an appointment, call or meeting
- notification: automated alerts from real services: security and fraud alerts
  (including from banks), password or sign-in notices, delivery updates, new orders.
  A real alert is NEVER spam, even if it mentions money.
- spam: unwanted mass marketing, newsletters, sales pitches, scams, phishing, prizes
- other: personal messages from friends or family, thank-you notes, and genuine
  one-to-one messages like a recruiter offering a job. These are NOT spam.

Urgency (do NOT default to medium; pick the level that fits):
- high: angry customer, money being lost, something broken, a deadline today or
  tomorrow, a change to a meeting that is today or tomorrow, or an alert where YOU
  must act soon (possible fraud, a new order to deliver, a failed payment)
- medium: a customer waiting for an answer within a few days
- low: newsletters, spam, general info, personal messages, no reply needed soon, and
  routine alerts where nothing needs doing (e.g. "if this was you, no action needed",
  delivery updates, password changed by you)

Meetings (only for the booking category, otherwise null):
- meeting_start: the date and time they asked for, as "YYYY-MM-DD HH:MM", worked out from today's date.
  If they give a day but no time, use 10:00 for morning, 14:00 for afternoon, otherwise 11:00.
  If they give several options, pick the earliest one that is in the future.
  If they give no day at all, use null.
- meeting_minutes: the length they asked for, otherwise 30.

Reply with JSON only, no other text, in this format:
{{"category": "...", "urgency": "...", "summary": "one sentence",
 "meeting_start": "YYYY-MM-DD HH:MM" or null, "meeting_minutes": 30,
 "draft_reply": "a short, friendly reply"}}

Rules for draft_reply:
- Never promise prices, refunds or deadlines.
- For a booking with a meeting_start, offer that exact day and time and ask them to confirm.
- For spam and notification, use an empty string.

Email:
"""


def ask_ai(prompt: str) -> str:
    """Send a prompt to Gemini, retrying if it's busy, and return the text answer."""
    for model in MODELS:
        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",  # ask for clean JSON
                        "temperature": 0,  # 0 = most consistent answers, less randomness
                    },
                )
                return response.text
            except (errors.ServerError, errors.ClientError) as e:
                code = getattr(e, "code", None)
                if code in (429, 500, 503):
                    wait = attempt * 5
                    print(f"    AI busy (error {code}), waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise  # a different problem, e.g. a wrong API key
    raise RuntimeError("All AI models are busy right now. Try again in a few minutes.")


def clean_meeting(result: dict) -> None:
    """Check the AI's meeting time in code: it must be a real date in the future."""
    start = result.get("meeting_start")
    try:
        when = datetime.strptime(str(start), "%Y-%m-%d %H:%M")
        if result.get("category") != "booking" or when <= datetime.now():
            raise ValueError
    except (TypeError, ValueError):
        result["meeting_start"] = None
    try:
        minutes = int(result.get("meeting_minutes") or 30)
    except (TypeError, ValueError):
        minutes = 30
    result["meeting_minutes"] = minutes if 5 <= minutes <= 240 else 30


def classify_email(sender: str, subject: str, body: str) -> dict:
    """Return the AI's category, urgency, summary, meeting time and draft reply for one email."""
    today = datetime.now().strftime("%A %d %B %Y, %H:%M")
    email_text = f"From: {sender}\nSubject: {subject}\n\n{body}"
    text = ask_ai(PROMPT.format(today=today) + email_text)
    # Keep only the part between the first { and the last }, just in case
    text = text[text.find("{"): text.rfind("}") + 1]
    result = json.loads(text)

    clean_meeting(result)

    # A hard rule in code, not left to the AI: never draft replies to no-reply addresses
    if any(word in sender.lower() for word in ("no-reply", "noreply", "donotreply", "do-not-reply")):
        result["draft_reply"] = ""
    return result
