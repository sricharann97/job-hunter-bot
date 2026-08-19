import os
import requests
from datetime import datetime

# ── Telegram Config ──────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ── Candidate Profile ─────────────────────────────────────────
KEYWORDS = [
    "Accounts Executive", "Accounts Assistant", "Junior Accountant",
    "Accountant Trainee", "Tally Operator", "GST Assistant",
    "GST Executive", "TDS Assistant", "Billing Executive",
    "Data Entry Accounts", "Finance Assistant", "Bookkeeper",
    "Back Office Finance", "MIS Executive"
]

LOCATIONS = ["Hyderabad", "Secunderabad", "Telangana", "Remote", "Work From Home"]

# ── Telegram Sender ───────────────────────────────────────────
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    requests.post(url, json=payload)

# ── Job Search — Indeed ───────────────────────────────────────
def search_indeed():
    jobs = []
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for keyword in KEYWORDS[:5]:  # top 5 roles
        for location in ["Hyderabad", "Remote"]:
            url = (
                f"https://indeed.com/jobs"
                f"?q={keyword.replace(' ', '+')}"
                f"&l={location}"
                f"&fromage=1"  # last 24 hours
                f"&explvl=entry_level"
            )
            jobs.append({
                "title": keyword,
                "location": location,
                "platform": "Indeed",
                "url": url
            })
    return jobs

# ── Job Search — Naukri ───────────────────────────────────────
def search_naukri():
    jobs = []
    for keyword in KEYWORDS[:5]:
        url = (
            f"https://www.naukri.com/"
            f"{keyword.lower().replace(' ', '-')}-jobs-in-hyderabad"
        )
        jobs.append({
            "title": keyword,
            "location": "Hyderabad",
            "platform": "Naukri",
            "url": url
        })
    return jobs

# ── Job Search — Internshala ──────────────────────────────────
def search_internshala():
    jobs = []
    for keyword in ["Accounts", "Tally", "GST", "Finance", "Data Entry"]:
        url = (
            f"https://internshala.com/jobs/"
            f"{keyword.lower()}-jobs-in-hyderabad"
        )
        jobs.append({
            "title": f"{keyword} Role",
            "location": "Hyderabad / Remote",
            "platform": "Internshala",
            "url": url
        })
    return jobs

# ── Format & Send Report ──────────────────────────────────────
def build_report(all_jobs):
    now        = datetime.now()
    period     = "🌅 Morning" if now.hour < 12 else "🌆 Evening"
    date_str   = now.strftime("%d %b %Y")
    time_str   = now.strftime("%I:%M %p")

    header = (
        f"📋 <b>JOB ALERT — {period} Report</b>\n"
        f"📅 {date_str} | ⏰ {time_str} IST\n"
        f"👤 Aadirala Sri Charan | Hyderabad\n"
        f"{'─'*30}\n\n"
    )

    body = ""
    for i, job in enumerate(all_jobs, 1):
        body += (
            f"🔥 <b>{i}. {job['title']}</b>\n"
            f"📍 {job['location']}\n"
            f"🌐 {job['platform']}\n"
            f"🔗 <a href='{job['url']}'>Apply Here</a>\n\n"
        )

    footer = (
        f"{'─'*30}\n"
        f"✅ Total Roles Found: {len(all_jobs)}\n"
        f"💡 Tip: Apply within 24hrs for fresher roles!\n"
        f"📧 aadiralasricharan@gmail.com\n"
        f"📞 9666915214"
    )

    return header + body + footer

# ── Main ──────────────────────────────────────────────────────
def main():
    print("🔍 Searching jobs...")

    all_jobs = []
    all_jobs += search_indeed()
    all_jobs += search_naukri()
    all_jobs += search_internshala()

    print(f"✅ Found {len(all_jobs)} job links")

    # Split into chunks (Telegram 4096 char limit)
    report = build_report(all_jobs)
    chunks = [report[i:i+4000] for i in range(0, len(report), 4000)]

    for chunk in chunks:
        send_telegram(chunk)

    print("📨 Report sent to Telegram!")

if __name__ == "__main__":
    main()
