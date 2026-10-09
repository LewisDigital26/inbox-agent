"""
accuracy_test.py - measures how accurately the AI sorts emails.

Runs 40 labelled test emails through the same AI your agent uses and scores it.
SAFE: nothing is sent, logged to the sheet or booked. It only calls the AI.
Takes about 3-4 minutes (it pauses between emails to stay inside the free AI limits).

Results are saved to accuracy_report.md and accuracy_results.csv in your project folder.
"""
import csv
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


def find_project() -> Path:
    here = Path(__file__).resolve().parent
    if (here / "ai.py").exists():
        return here
    home = Path.home()
    for desktop in (home / "OneDrive" / "Desktop", home / "Desktop"):
        if (desktop / "inbox-agent" / "ai.py").exists():
            return desktop / "inbox-agent"
    raise FileNotFoundError("Couldn't find your inbox-agent folder.")


FOLDER = find_project()
VENV_PYTHON = FOLDER / "venv" / "Scripts" / "python.exe"
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    subprocess.run([str(VENV_PYTHON), str(Path(__file__).resolve())], cwd=FOLDER)
    sys.exit()
os.chdir(FOLDER)
sys.path.insert(0, str(FOLDER))

# Each test: (sender, subject, body, correct category, correct urgency, should a meeting time be found?)
TESTS = [
    # ---- enquiry ----
    ("sarah@bakery-example.co.uk", "Website for my bakery",
     "Hi, I run a small bakery and need a simple website with an online menu. How much would that cost and how long would it take?",
     "enquiry", "medium", False),
    ("tom.h@example.com", "Logo design?",
     "Do you do logo design as well as websites? I'm starting a dog walking business. Just looking at options for now.",
     "enquiry", "low", False),
    ("info@cafe-example.com", "Instagram help",
     "We're a cafe in Coventry and want help running our Instagram. Do you offer monthly packages? We'd like to start this month if possible.",
     "enquiry", "medium", False),
    ("j.patel@example.com", "Spreadsheet work",
     "Hi there, could you build a spreadsheet to track stock for my shop? What would you need from me to give a quote?",
     "enquiry", "medium", False),
    ("mike@builders-example.co.uk", "Quote needed by tomorrow",
     "I need a quote for a 5 page website by tomorrow lunchtime as I'm presenting it to my business partner. Can you help?",
     "enquiry", "high", False),
    ("amy.r@example.com", "Do you still offer VA services?",
     "Saw your Fiverr profile a while ago. Are you still offering virtual assistant work? No rush, just planning ahead for next year.",
     "enquiry", "low", False),
    ("hello@florist-example.com", "Prices for presentations",
     "How much do you charge to design a 10 slide pitch deck? We need it in the next couple of weeks.",
     "enquiry", "medium", False),

    # ---- complaint ----
    ("mark.d@example.com", "Website down AGAIN",
     "My website has been down for two days and I've lost orders. This is unacceptable. Fix it today or I want a refund.",
     "complaint", "high", False),
    ("karen@example.com", "Typos on my site",
     "Hi, I noticed a few spelling mistakes on the About page you made for me. Not urgent, but could you fix them when you get a chance?",
     "complaint", "low", False),
    ("dave@garage-example.co.uk", "Contact form not working",
     "Customers are telling me the contact form on my site isn't sending anything. I'm probably missing bookings. Please look at this ASAP.",
     "complaint", "high", False),
    ("lucy@example.com", "Disappointed with the logo",
     "I have to be honest, the final logo isn't what we discussed. The colours are wrong. Can we talk about how to put it right this week?",
     "complaint", "medium", False),
    ("ben@example.com", "Charged twice",
     "I've been charged twice for the same invoice. I need the extra payment refunded, this has left me short this month.",
     "complaint", "high", False),
    ("sue@example.com", "Slow replies",
     "Bit frustrated that it took a week to hear back last time. Could replies be a bit quicker going forward?",
     "complaint", "medium", False),

    # ---- invoice ----
    ("accounts@hosting-example.com", "Invoice INV-2041 for October hosting",
     "Please find attached invoice INV-2041 for £12.99 for October web hosting. Payment due within 30 days.",
     "invoice", "low", False),
    ("raj@example.com", "Payment sent",
     "Just to let you know I've sent the £150 for the website work by bank transfer this morning. Thanks!",
     "invoice", "low", False),
    ("billing@software-example.com", "Payment failed - action needed",
     "We couldn't take payment for your subscription. Please update your card within 3 days or your account will be suspended.",
     "invoice", "high", False),
    ("emma@example.com", "Can I get an invoice?",
     "Could you send me an invoice for last month's admin work so I can put it through my accounts? Need it by the end of next week.",
     "invoice", "medium", False),
    ("finance@agency-example.com", "Remittance advice",
     "Remittance advice: payment of £320.00 has been made to your account for invoice LD-007.",
     "invoice", "low", False),

    # ---- booking ----
    ("priya@example.com", "Quick call?",
     "Hi, could we have a 30 minute call next Tuesday at 3pm about a new website? Thanks, Priya",
     "booking", "medium", True),
    ("owen@example.com", "Meeting next week",
     "Are you free on Wednesday afternoon next week to go through the designs? An hour should be enough.",
     "booking", "medium", True),
    ("chloe@example.com", "Can we move our call?",
     "Something's come up. Could we move tomorrow's call to Friday at 10am instead?",
     "booking", "high", True),
    ("nina@example.com", "Cancel Thursday",
     "Sorry, I need to cancel our meeting on Thursday. I'll be in touch to rearrange.",
     "booking", "medium", False),
    ("sam@example.com", "Let's chat",
     "Would love to book in a chat about social media help. When are you free?",
     "booking", "medium", False),
    ("leo@example.com", "Consultation tomorrow morning?",
     "Is there any chance of a quick 15 minute consultation tomorrow morning? I've got a launch coming up.",
     "booking", "high", True),
    ("grace@example.com", "Book a session",
     "I'd like to book a 45 minute training session on Canva for my team on Monday at 11am please.",
     "booking", "medium", True),

    # ---- notification ----
    ("no-reply@accounts.google.com", "Security alert",
     "A new sign-in to your Google Account was detected on a Windows device. If this was you, you don't need to do anything.",
     "notification", "low", False),
    ("noreply@delivery-example.com", "Your parcel is on its way",
     "Good news! Your order #48213 has been dispatched and will arrive tomorrow between 9am and 1pm.",
     "notification", "low", False),
    ("no-reply@bank-example.co.uk", "Unusual activity on your account",
     "We've noticed a payment of £499 that doesn't look like you. Please check your banking app now. We will never ask for your password.",
     "notification", "high", False),
    ("noreply@fiverr-example.com", "You have a new order",
     "Congratulations! You've received a new order for 'Website design'. Please deliver within 3 days.",
     "notification", "high", False),
    ("no-reply@github-example.com", "Password changed",
     "The password for your account was changed. If you made this change, no further action is needed.",
     "notification", "low", False),

    # ---- spam ----
    ("deals@newsletter.games-example.com", "New Mafia III Update",
     "Check out the latest update and save 75% on games this weekend only!",
     "spam", "low", False),
    ("winner@prize-example.biz", "You've WON £1,000,000!!!",
     "Congratulations! You have been selected as our lucky winner. Send your bank details to claim your prize now.",
     "spam", "low", False),
    ("seo@marketing-example.net", "Rank #1 on Google",
     "Hi, I noticed your website isn't ranking. Our SEO team can get you to page one guaranteed. Reply for a free audit.",
     "spam", "low", False),
    ("support@paypa1-secure-example.com", "Your invoice is overdue - pay now",
     "Dear customer, your invoice is overdue. Click this link and log in to avoid legal action: http://paypa1-secure-example.com/login",
     "spam", "low", False),
    ("crypto@invest-example.io", "Double your money",
     "Our AI crypto bot doubles your money in 7 days. Limited spots. Invest now!",
     "spam", "low", False),
    ("offers@shop-example.com", "Black Friday early access",
     "Get early access to our Black Friday sale. Up to 60% off everything.",
     "spam", "low", False),

    # ---- other ----
    ("mum@example.com", "Sunday dinner",
     "Are you coming for dinner on Sunday? Let me know so I can get enough food in.",
     "other", "low", False),
    ("alex@example.com", "Thanks!",
     "Just wanted to say thanks again for the website, really happy with it. No need to reply.",
     "other", "low", False),
    ("jobs@recruiter-example.com", "AI automation role",
     "Hi Lewis, I came across your profile and have a junior AI automation role in Birmingham. Would you be open to a chat?",
     "other", "medium", False),
    ("chris@example.com", "Football Saturday",
     "Five-a-side is on Saturday at 10. You in?",
     "other", "low", False),
]


# HOLD-OUT SET: fresh emails that were NEVER used to tune the prompt.
# Use these for the honest final score. Don't change the prompt based on them.
HOLDOUT = [
    ("rachel@salon-example.co.uk", "Booking system for my salon",
     "Hi, I'm opening a hair salon in the spring and want a website where clients can book online. Could you give me a rough idea of cost?",
     "enquiry", "low", False),
    ("pete@example.com", "Wrong phone number on website",
     "The phone number on my homepage is wrong, customers can't get through to me at all. Please sort it today.",
     "complaint", "high", False),
    ("accounts@domain-example.com", "Your domain renews in 30 days",
     "Your domain signaltradingbot.online will renew automatically in 30 days for £9.99.",
     "invoice", "low", False),
    ("hannah@example.com", "Call on Thursday?",
     "Could we do a 20 minute call this Thursday at 1pm to go over the spreadsheet? Thanks!",
     "booking", "medium", True),
    ("noreply@cloudflare-example.com", "New login to your account",
     "We detected a login to your account from a new device in London. If this was you, you can ignore this email.",
     "notification", "low", False),
    ("promo@vpn-example.com", "80% off VPN - today only!",
     "Protect yourself online with 80% off our premium VPN. Offer ends at midnight!",
     "spam", "low", False),
    ("nan@example.com", "Happy birthday love",
     "Happy birthday! Hope you have a lovely day. Ring me when you get a minute x",
     "other", "low", False),
    ("director@agency-example.co.uk", "Invoice query",
     "Your invoice LD-012 says 10 hours but we agreed on 8. Can you send a corrected one? Not happy about this.",
     "complaint", "medium", False),
    ("security@micros0ft-help-example.com", "Your account will be deleted",
     "We detected a problem with your account. Verify your password within 24 hours at this link or it will be deleted.",
     "spam", "low", False),
    ("tasha@example.com", "Help with newsletters",
     "Do you write email newsletters for small businesses? We send one a month and need someone to take it over from next month.",
     "enquiry", "medium", False),
    ("joe@example.com", "Change of plan",
     "Sorry, something's come up. Could we move our call tomorrow from 2pm to 4pm instead?",
     "booking", "high", True),
    ("noreply@etsy-example.com", "Payment received",
     "You've received a payment of £45.00 for order #1182. The money will be in your account in 3 days.",
     "invoice", "low", False),
]


def main():
    from ai import classify_email

    global TESTS
    print("Which test do you want to run?")
    print("  1 = main test (40 emails, used to improve the prompt)")
    print("  2 = hold-out test (12 fresh emails, the honest final score)")
    choice = input("Type 1 or 2 and press Enter: ").strip()
    suffix = ""
    if choice == "2":
        TESTS, suffix = HOLDOUT, "_holdout"

    print(f"\nRunning {len(TESTS)} test emails through the AI. This takes a few minutes...\n")
    rows = []
    for i, (sender, subject, body, want_cat, want_urg, want_meeting) in enumerate(TESTS, start=1):
        try:
            result = classify_email(sender, subject, body)
            got_cat, got_urg = result.get("category", "?"), result.get("urgency", "?")
            got_meeting = bool(result.get("meeting_start"))
            error = ""
        except Exception as e:
            got_cat = got_urg = "ERROR"
            got_meeting, error = False, str(e)

        cat_ok, urg_ok = got_cat == want_cat, got_urg == want_urg
        meeting_ok = got_meeting == want_meeting if want_cat == "booking" else None
        mark = "OK " if cat_ok else "XX "
        print(f"{i:2}. {mark} {subject[:40]:40}  want {want_cat:12} got {got_cat:12}"
              f"  urgency {'ok' if urg_ok else f'{got_urg} (want {want_urg})'}")
        rows.append({"#": i, "subject": subject, "expected_category": want_cat, "ai_category": got_cat,
                     "category_correct": cat_ok, "expected_urgency": want_urg, "ai_urgency": got_urg,
                     "urgency_correct": urg_ok, "meeting_check": "" if meeting_ok is None else meeting_ok,
                     "error": error})
        time.sleep(4)  # stay inside the free AI rate limits

    total = len(rows)
    cat_score = sum(r["category_correct"] for r in rows)
    urg_score = sum(r["urgency_correct"] for r in rows)
    meeting_rows = [r for r in rows if r["meeting_check"] != ""]
    meet_score = sum(r["meeting_check"] for r in meeting_rows)
    mistakes = Counter((r["expected_category"], r["ai_category"]) for r in rows if not r["category_correct"])

    per_cat = {}
    for r in rows:
        c = r["expected_category"]
        per_cat.setdefault(c, [0, 0])
        per_cat[c][0] += r["category_correct"]
        per_cat[c][1] += 1

    lines = [
        "# AI Inbox Agent: accuracy report",
        "",
        f"Run on {datetime.now().strftime('%d %B %Y %H:%M')} with {total} labelled test emails.",
        "",
        "| Measure | Score |",
        "| --- | --- |",
        f"| Category | {cat_score}/{total} ({cat_score / total:.0%}) |",
        f"| Urgency | {urg_score}/{total} ({urg_score / total:.0%}) |",
        f"| Meeting time found correctly (bookings) | {meet_score}/{len(meeting_rows)} |",
        "",
        "## By category",
        "",
        "| Category | Correct |",
        "| --- | --- |",
        *[f"| {c} | {ok}/{n} |" for c, (ok, n) in per_cat.items()],
        "",
        "## Mistakes",
        "",
    ]
    if mistakes:
        lines += [f"- expected **{want}**, AI said **{got}** ({n}x)" for (want, got), n in mistakes.most_common()]
    else:
        lines.append("None.")

    if suffix:
        lines[0] += " (hold-out set)"
    (FOLDER / f"accuracy_report{suffix}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(FOLDER / f"accuracy_results{suffix}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("\n" + "=" * 60)
    print(f"CATEGORY ACCURACY: {cat_score}/{total} ({cat_score / total:.0%})")
    print(f"URGENCY ACCURACY:  {urg_score}/{total} ({urg_score / total:.0%})")
    print(f"MEETING TIMES:     {meet_score}/{len(meeting_rows)} bookings handled correctly")
    if mistakes:
        print("\nMistakes:")
        for (want, got), n in mistakes.most_common():
            print(f"  expected {want}, AI said {got} ({n}x)")
    print("=" * 60)
    print(f"Saved accuracy_report{suffix}.md and accuracy_results{suffix}.csv in your project folder.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nSomething went wrong: {e}")
    input("\nPress Enter to close...")
