"""Hyderabad job hunter with formatted Telegram notifications.

Required environment variables:
  TELEGRAM_TOKEN       Telegram bot token (GitHub Actions Secret)
  TELEGRAM_CHAT_ID     Destination chat ID (GitHub Actions Secret)

Set DRY_RUN=1 to print notifications without sending them.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

import requests

# --- Configuration ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DRY_RUN = os.getenv("DRY_RUN", "0").lower() in {"1", "true", "yes"}
API_URL = "https://www.arbeitnow.com/api/job-board-api"
SEEN_FILE = "seen_jobs.json"
TELEGRAM_TIMEOUT_SECONDS = 15
MAX_TELEGRAM_LENGTH = 4096

# Hyderabad-only target terms. The source API may return international/remote roles,
# so location checks are applied separately in is_hyderabad_job().
TARGET_KEYWORDS = [
    "accountant",
    "accounts executive",
    "billing executive",
    "medical billing",
    "revenue cycle",
    "accounts receivable",
    "finance operations",
    "tally",
    "gst",
    "audit assistant",
]
HYDERABAD_TERMS = {"hyderabad", "hitech city", "hitec city", "secunderabad"}


def esc(value: Any, fallback: str = "Not specified") -> str:
    """Escape untrusted job text before inserting it into Telegram HTML."""
    text = fallback if value is None or str(value).strip() == "" else str(value).strip()
    return html.escape(text, quote=True)


def short(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def field(label: str, value: Any, fallback: str = "Not specified") -> str:
    return f"<b>{esc(label)}:</b> {esc(value, fallback)}"


def job_details(job: Mapping[str, Any]) -> str:
    """Common job details used by NEW JOB and APPLIED notifications."""
    title = job.get("title") or job.get("role") or "Untitled role"
    company = job.get("company") or job.get("company_name")
    location = job.get("location")
    experience = job.get("experience") or job.get("experience_required")
    salary = job.get("salary") or job.get("salary_range")
    source = job.get("source") or job.get("portal")
    match_score = job.get("match_score")
    qualification = job.get("qualification") or job.get("education")
    shift = job.get("shift")
    walk_in = job.get("walk_in") or job.get("walkin")
    posted = job.get("posted_date") or job.get("date_posted")
    applied = job.get("application_status") or job.get("applied")
    route = job.get("application_route") or job.get("route")
    follow_up = job.get("follow_up_date")
    link = job.get("link") or job.get("url")

    lines = [
        field("Role", title),
        field("Company", company),
        field("Location", location),
        field("Experience", experience, "Fresher / not specified"),
        field("Match score", f"{match_score}%" if match_score is not None else None),
        field("Qualification", qualification),
        field("Salary", salary),
        field("Shift", shift),
        field("Walk-in", walk_in),
        field("Posted", posted),
        field("Source", source),
        field("Application", applied),
        field("Route", route),
        field("Follow-up", follow_up),
    ]
    lines = [line for line in lines if "Not specified" not in line]
    if link:
        lines.append(f"🔗 <a href=\"{esc(link)}\">Open listing</a>")
    return "\n".join(lines)


def template_new_job(job: Mapping[str, Any]) -> str:
    return (
        "🆕 <b>NEW JOB — Hyderabad Match</b>\n\n"
        f"{job_details(job)}\n\n"
        "✅ <b>Next step:</b> Verify the employer and check for duplicates before applying."
    )


def template_red_alert(alert: Mapping[str, Any]) -> str:
    category = alert.get("category") or "Recruiter update"
    subject = alert.get("subject") or alert.get("role") or "Important recruiter message"
    company = alert.get("company")
    sender = alert.get("sender") or alert.get("email")
    action = alert.get("action") or "Review the message and respond promptly."
    message_link = alert.get("message_link")
    lines = [
        "🚨 <b>RED ALERT — Recruiter / Interview Update</b>",
        "",
        field("Type", category),
        field("Subject", subject),
        field("Company", company),
        field("From", sender),
        field("Action", action),
    ]
    snippet = short(alert.get("snippet"), 700)
    if snippet:
        lines.extend(["", f"<b>Preview:</b> {esc(snippet)}"])
    if message_link:
        lines.extend(["", f"📨 <a href=\"{esc(message_link)}\">Open recruiter message</a>"])
    return "\n".join(line for line in lines if line != "")


def template_report(report: Mapping[str, Any]) -> str:
    period = report.get("period") or "Latest run"
    lines = [
        "📊 <b>REPORT — Job Hunter Summary</b>",
        "",
        field("Period", period),
        field("Jobs scanned", report.get("jobs_scanned"), "0"),
        field("New matches", report.get("new_matches"), "0"),
        field("Applications sent", report.get("applications_sent"), "0"),
        field("Duplicates skipped", report.get("duplicates_skipped"), "0"),
        field("Rejected / filtered", report.get("rejected"), "0"),
        field("Recruiter replies", report.get("recruiter_replies"), "0"),
        field("Interview invitations", report.get("interviews"), "0"),
        field("Errors", report.get("errors"), "0"),
    ]
    notes = short(report.get("notes"), 600)
    if notes:
        lines.extend(["", f"📝 <b>Notes:</b> {esc(notes)}"])
    return "\n".join(lines)


def template_applied(job: Mapping[str, Any]) -> str:
    return (
        "📨 <b>APPLIED — Application Submitted</b>\n\n"
        f"{job_details(job)}\n\n"
        "📎 <b>Resume:</b> Sricharan_Resume_.pdf"
    )


def template_skipped(job: Mapping[str, Any], reason: str) -> str:
    return (
        "⏭️ <b>SKIPPED — No Application Sent</b>\n\n"
        f"{job_details(job)}\n\n"
        f"⚠️ <b>Reason:</b> {esc(reason)}"
    )


def template_error(error: Mapping[str, Any] | str) -> str:
    if isinstance(error, Mapping):
        stage = error.get("stage") or "Workflow"
        details = error.get("message") or error.get("details") or "Unknown error"
    else:
        stage, details = "Workflow", error
    return (
        "❌ <b>ERROR — Job Hunter Problem</b>\n\n"
        f"{field('Stage', stage)}\n"
        f"{field('Details', short(details, 900))}\n\n"
        "🔧 The run stopped safely. No application should be assumed unless an APPLIED alert was sent."
    )


def render_notification(category: str, data: Mapping[str, Any]) -> str:
    """Render one supported category into Telegram HTML."""
    normalized = category.upper().replace(" ", "_")
    renderers = {
        "NEW_JOB": template_new_job,
        "RED_ALERT": template_red_alert,
        "REPORT": template_report,
        "APPLIED": template_applied,
        "SKIPPED": lambda value: template_skipped(value, str(data.get("reason", "Filtered"))),
        "ERROR": template_error,
    }
    if normalized not in renderers:
        raise ValueError(f"Unsupported notification category: {category}")
    message = renderers[normalized](data)
    return message[:MAX_TELEGRAM_LENGTH]


def send_telegram_alert(message: str) -> bool:
    """Send HTML to Telegram, or print it in dry-run mode. Never logs the bot token."""
    if DRY_RUN:
        print("--- TELEGRAM DRY RUN ---")
        print(message)
        return True
    if not TELEGRAM_TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be configured")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, data=payload, timeout=TELEGRAM_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram API returned ok=false")
    return True


def notify(category: str, data: Mapping[str, Any]) -> bool:
    """Render and deliver a notification. Caller decides whether to continue on failure."""
    try:
        return send_telegram_alert(render_notification(category, data))
    except Exception as exc:
        print(f"Telegram notification failed for {category}: {type(exc).__name__}: {exc}")
        return False


def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as file:
                return set(json.load(file).get("seen", []))
        except (OSError, ValueError, TypeError):
            print("Warning: seen_jobs.json could not be read; starting with an empty set.")
    return set()


def save_seen(seen: set[str]) -> None:
    data = {"last_run_utc": datetime.now(timezone.utc).isoformat(), "seen": sorted(seen)}
    with open(SEEN_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def is_hyderabad_job(job: Mapping[str, Any]) -> bool:
    location = str(job.get("location") or "").lower()
    description = str(job.get("description") or "").lower()
    return any(term in f"{location} {description}" for term in HYDERABAD_TERMS)


def fetch_commerce_jobs() -> None:
    seen = load_seen()
    alerts_sent = 0
    skipped = 0

    try:
        response = requests.get(API_URL, timeout=TELEGRAM_TIMEOUT_SECONDS)
        response.raise_for_status()
        jobs = response.json().get("data", [])
    except Exception as exc:
        print(f"Error fetching jobs: {type(exc).__name__}: {exc}")
        notify("ERROR", {"stage": "Job source", "message": str(exc)})
        save_seen(seen)
        return

    for job in jobs[:50]:
        title = str(job.get("title") or "")
        description = str(job.get("description") or "")
        link = str(job.get("url") or "")
        if not link or link in seen:
            continue

        haystack = f"{title} {description}".lower()
        if not any(keyword in haystack for keyword in TARGET_KEYWORDS) or not is_hyderabad_job(job):
            skipped += 1
            seen.add(link)
            continue

        notification_job = {
            "title": title,
            "company": job.get("company_name"),
            "location": job.get("location"),
            "experience": "Fresher / verify listing",
            "source": "Arbeitnow",
            "application_status": "Not yet applied",
            "link": link,
        }
        if notify("NEW_JOB", notification_job):
            alerts_sent += 1
        seen.add(link)

    save_seen(seen)
    notify(
        "REPORT",
        {
            "period": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "jobs_scanned": len(jobs[:50]),
            "new_matches": alerts_sent,
            "applications_sent": 0,
            "duplicates_skipped": len(seen) - alerts_sent,
            "rejected": skipped,
            "recruiter_replies": 0,
            "interviews": 0,
            "errors": 0,
        },
    )
    print(f"Run complete. {alerts_sent} new alert(s) sent; {len(seen)} jobs tracked total.")


if __name__ == "__main__":
    fetch_commerce_jobs()
