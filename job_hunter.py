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
import re
from datetime import datetime, timezone
from typing import Any, Mapping

import requests
from bs4 import BeautifulSoup

# --- Configuration ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DRY_RUN = os.getenv("DRY_RUN", "0").lower() in {"1", "true", "yes"}
SEEN_FILE = "seen_jobs.json"
TELEGRAM_TIMEOUT_SECONDS = 15
MAX_TELEGRAM_LENGTH = 4096
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HyderabadJobHunter/1.0; public-job-discovery)",
    "Accept-Language": "en-IN,en;q=0.9",
}
SEARCH_QUERIES = [
    "hospital billing",
    "OPD IPD billing",
    "medical billing",
    "data entry",
    "back office executive",
]

# Hyderabad-only target terms. The source API may return international/remote roles,
# so location checks are applied separately in is_hyderabad_job().
TARGET_KEYWORDS = [
    "accountant",
    "accounts executive",
    "billing executive",
    "hospital billing",
    "opd billing",
    "ipd billing",
    "patient billing",
    "cash billing",
    "discharge billing",
    "front office billing",
    "medical billing",
    "data entry",
    "data entry operator",
    "computer operator",
    "back office executive",
    "back office assistant",
    "office assistant",
    "office administrator",
    "administrative assistant",
    "admin executive",
    "documentation executive",
    "non voice process",
    "revenue cycle",
    "accounts receivable",
    "finance operations",
    "tally",
    "gst",
    "audit assistant",
]
HYDERABAD_TERMS = {"hyderabad", "hitech city", "hitec city", "secunderabad"}
EXPERIENCE_REQUIRED_PATTERNS = (
    r"experience\s+(?:is\s+)?(?:mandatory|required|must|required)",
    r"minimum\s+(?:of\s+)?[1-9]\d*\s*\+?\s*years?",
    r"[2-9]\s*[-–]\s*[0-9]+\s*years?",
    r"mid[- ]senior",
    r"senior\s+(?:level|accountant|executive|associate|analyst)",
)


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


def match_score(job: Mapping[str, Any]) -> float:
    """Deterministic fit score for ranking alerts; not an employer guarantee."""
    text = f"{job.get('title', '')} {job.get('description', '')}".lower()
    score = 45.0
    if any(term in text for term in ("hospital billing", "opd billing", "ipd billing", "medical billing")):
        score += 20
    elif any(term in text for term in ("billing", "data entry", "back office", "office assistant")):
        score += 15
    if any(term in text for term in ("b.com", "commerce", "tally", "gst")):
        score += 15
    if any(term in text for term in ("fresher", "0-1 yrs", "0-1 year", "entry level")):
        score += 10
    if job.get("source") == "LinkedIn":
        score += 5
    return min(99.0, round(score, 1))


def template_job_alert_report(jobs: list[Mapping[str, Any]]) -> str:
    lines = [
        f"📋 <b>JOB ALERT REPORT ({len(jobs)})</b>",
        "<i>Hyderabad Billing, Data Entry &amp; Desk Jobs — Scored &amp; Filtered</i>",
        "",
    ]
    for job in jobs:
        score = job.get("match_score", match_score(job))
        title = esc(job.get("title"), "Untitled role")
        company = esc(job.get("company"), "Company not specified")
        source = esc(job.get("source"), "Public job board")
        link = job.get("link") or job.get("url")
        lines.extend([
            f"⭐ <b>{score} | {title}</b>",
            f"🏢 {company} ({source})",
            f"🔗 <a href=\"{esc(link)}\">View Job</a>" if link else "🔗 Link unavailable",
            "",
        ])
    return "\n".join(lines).strip()[:MAX_TELEGRAM_LENGTH]


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
        field("Non-Hyderabad", report.get("non_hyderabad"), "0"),
        field("Experience mismatch", report.get("experience_mismatch"), "0"),
        field("Keyword mismatch", report.get("keyword_mismatch"), "0"),
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
        "JOB_ALERT_REPORT": template_job_alert_report,
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


def is_fresher_friendly(job: Mapping[str, Any]) -> bool:
    """Reject explicit experience requirements; preferred experience is allowed."""
    title = str(job.get("title") or "").lower()
    description = str(job.get("description") or "").lower()
    text = f"{title} {description}"
    if any(re.search(pattern, text) for pattern in EXPERIENCE_REQUIRED_PATTERNS):
        return False
    if re.search(r"\b(?:senior|lead|manager)\b", title):
        return False
    return True


def normalize_link(link: str, source: str) -> str:
    """Keep public job URLs stable enough for deduplication."""
    if link.startswith("/"):
        roots = {
            "Indeed": "https://in.indeed.com",
            "LinkedIn": "https://www.linkedin.com",
            "Naukri": "https://www.naukri.com",
        }
        link = roots[source] + link
    return link.split("?")[0]


def text_or_empty(node: Any) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def parse_indeed(html_text: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    jobs = []
    for card in soup.select("div.job_seen_beacon"):
        anchor = card.select_one("h2.jobTitle a, a.jcs-JobTitle")
        if not anchor:
            continue
        jobs.append({
            "title": text_or_empty(anchor),
            "company_name": text_or_empty(card.select_one("span.companyName")),
            "location": text_or_empty(card.select_one("div.companyLocation")),
            "description": text_or_empty(card.select_one("div.job-snippet")),
            "url": normalize_link(anchor.get("href", ""), "Indeed"),
            "source": "Indeed",
        })
    return jobs


def parse_linkedin(html_text: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    jobs = []
    for card in soup.select("div.base-card, li.jobs-search__results-list, div.job-search-card"):
        anchor = card.select_one("a.base-card__full-link, a.base-card__primary-link, a[href*='/jobs/view/']")
        title_node = card.select_one("h3.base-search-card__title, h3.base-card__full-link")
        company_node = card.select_one("h4.base-search-card__subtitle, a.hidden-nested-link")
        location_node = card.select_one("span.job-search-card__location, span.job-card-container__metadata-item")
        if not anchor or not title_node:
            continue
        jobs.append({
            "title": text_or_empty(title_node),
            "company_name": text_or_empty(company_node),
            "location": text_or_empty(location_node),
            "description": text_or_empty(card),
            "url": normalize_link(anchor.get("href", ""), "LinkedIn"),
            "source": "LinkedIn",
        })
    return jobs


def parse_naukri(html_text: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    jobs = []
    for card in soup.select("article.jobTuple, div.jobTuple, div.srp-jobtuple-wrapper"):
        anchor = card.select_one("a.title, a[href*='/job-listings-']")
        if not anchor:
            continue
        jobs.append({
            "title": text_or_empty(anchor),
            "company_name": text_or_empty(card.select_one("span.comp-name, a.subTitle")),
            "location": text_or_empty(card.select_one("span.locWdth, span.loc")),
            "experience": text_or_empty(card.select_one("span.expwdth, span.exp")),
            "description": text_or_empty(card),
            "url": normalize_link(anchor.get("href", ""), "Naukri"),
            "source": "Naukri",
        })
    return jobs


def fetch_public_board(source: str, query: str) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch only public search pages; never logs in or bypasses CAPTCHA/403 responses."""
    from urllib.parse import quote_plus

    urls = {
        "Indeed": f"https://in.indeed.com/jobs?q={quote_plus(query)}&l=Hyderabad%2C+Telangana",
        "LinkedIn": f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(query)}&location=Hyderabad%2C%20Telangana",
        "Naukri": f"https://www.naukri.com/{quote_plus(query.replace(' ', '-'))}-jobs-in-hyderabad-secunderabad",
    }
    parsers = {"Indeed": parse_indeed, "LinkedIn": parse_linkedin, "Naukri": parse_naukri}
    try:
        response = requests.get(urls[source], headers=REQUEST_HEADERS, timeout=TELEGRAM_TIMEOUT_SECONDS)
        if response.status_code in {401, 403, 429}:
            return [], f"{source} returned HTTP {response.status_code}; public page skipped"
        response.raise_for_status()
        return parsers[source](response.text), None
    except Exception as exc:
        return [], f"{source} {type(exc).__name__}: {short(exc, 180)}"


def fetch_live_jobs() -> tuple[list[dict[str, Any]], list[str]]:
    jobs: list[dict[str, Any]] = []
    source_errors: list[str] = []
    for source in ("Indeed", "LinkedIn", "Naukri"):
        for query in SEARCH_QUERIES:
            found, error = fetch_public_board(source, query)
            jobs.extend(found)
            if error:
                source_errors.append(error)
    unique: dict[str, dict[str, Any]] = {}
    for job in jobs:
        link = str(job.get("url") or "")
        if link and link not in unique:
            unique[link] = job
    return list(unique.values()), source_errors


def fetch_commerce_jobs() -> None:
    seen = load_seen()
    alerts_sent = 0
    matched_jobs: list[dict[str, Any]] = []
    skipped = 0
    duplicates_skipped = 0
    non_hyderabad = 0
    experience_mismatch = 0
    keyword_mismatch = 0
    jobs, source_errors = fetch_live_jobs()
    if source_errors:
        print("Public source warnings: " + " | ".join(source_errors))

    for job in jobs[:300]:
        title = str(job.get("title") or "")
        description = str(job.get("description") or "")
        link = str(job.get("url") or "")
        if not link or link in seen:
            duplicates_skipped += 1
            continue

        haystack = f"{title} {description}".lower()
        if not any(keyword in haystack for keyword in TARGET_KEYWORDS):
            keyword_mismatch += 1
            skipped += 1
            seen.add(link)
            continue
        if not is_hyderabad_job(job):
            non_hyderabad += 1
            skipped += 1
            seen.add(link)
            continue
        if not is_fresher_friendly(job):
            experience_mismatch += 1
            skipped += 1
            seen.add(link)
            continue

        notification_job = {
            "title": title,
            "company": job.get("company_name"),
            "location": job.get("location"),
            "experience": "Fresher / verify listing",
            "source": job.get("source") or "Public job board",
            "application_status": "Not yet applied",
            "link": link,
            "description": description,
        }
        notification_job["match_score"] = match_score(notification_job)
        matched_jobs.append(notification_job)
        seen.add(link)

    for start in range(0, len(matched_jobs), 8):
        batch = matched_jobs[start : start + 8]
        if notify("JOB_ALERT_REPORT", batch):
            alerts_sent += len(batch)

    save_seen(seen)
    notify(
        "REPORT",
        {
            "period": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "jobs_scanned": len(jobs[:300]),
            "new_matches": alerts_sent,
            "applications_sent": 0,
            "duplicates_skipped": duplicates_skipped,
            "rejected": skipped,
            "non_hyderabad": non_hyderabad,
            "experience_mismatch": experience_mismatch,
            "keyword_mismatch": keyword_mismatch,
            "recruiter_replies": 0,
            "interviews": 0,
            "errors": len(source_errors),
            "notes": "; ".join(source_errors[:3]) if source_errors else "Live public pages checked: Indeed, LinkedIn, Naukri",
        },
    )
    print(f"Run complete. {alerts_sent} new alert(s) sent; {len(seen)} jobs tracked total.")


if __name__ == "__main__":
    fetch_commerce_jobs()
