import os

import json

import time

from datetime import datetime, timezone, timedelta



import requests



# ── Telegram Config ──────────────────────────────────────────

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]



# ── Candidate Profile ────────────────────────────────────────

# Lowercase-only: the script lowercases job text before matching.

KEYWORDS = [
    
    "accounts executive", "accounts assistant", "junior accountant",
    
    "accountant trainee", "tally operator", "gst assistant",
    
    "gst executive", "tds assistant", "billing executive",
    
    "finance assistant", "bookkeeper", "back office finance",
    
    "mis executive", "accountant", "finance", "accounting",
    
    "tally", "audit", "clerk", "data entry", "admin",
    
]



# ── Seen-job tracking (dedup) ────────────────────────────────

SEEN_FILE = "seen_jobs.json"

# A job link older than this stops generating alerts (feed churn). 30 days.

FRESHNESS_DAYS = 30





def load_seen():
    
    if os.path.exists(SEEN_FILE):
        
        with open(SEEN_FILE, "r") as f:
            
            data = json.load(f)
            
            # {url: iso_timestamp}

            return data.get("seen", {})
            
    return {}
    




def save_seen(seen):
    
    # Purge very old entries so the file stays small.
    
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    
    seen = {u: t for u, t in seen.items() if t > cutoff}
    
    with open(SEEN_FILE, "w") as f:
        
        json.dump({"last_run_utc": datetime.now(timezone.utc).isoformat(),
                   
                   "seen": seen}, f, indent=2)
        




# ── Telegram Sender ──────────────────────────────────────────

def send_telegram(message):
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    payload = {
        
        "chat_id": TELEGRAM_CHAT_ID,
        
        "text": message,
        
        "parse_mode": "HTML",
        
        "disable_web_page_preview": False,
        
    }
    
    try:
        
        r = requests.post(url, json=payload, timeout=15)
        
        print(f"Telegram HTTP {r.status_code}")
        
    except Exception as e:
        
        print(f"Telegram send failed: {e}")
        




# ── Source 1: Arbeitsnow (Germany + Remote) ──────────────────

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"





def fetch_arbeitnow():
    
    """Real individual listings: title, company, location, apply URL, description."""
    
    r = requests.get(ARBEITNOW_URL, timeout=20)
    
    r.raise_for_status()
    
    jobs = []
    
    for j in r.json().get("data", [])[:200]:
        
        jobs.append({
            "id": j.get("slug", j.get("url", "")),
            "title": j.get("title", ""),
            "company": j.get("company_name", "Unknown"),
            "location": j.get("location", "Not specified"),
            "url": j.get("url", ""),
            "posted": (j.get("date") or "")[:10],
            "haystack": (f"{j.get('title','')} {j.get('description','')} {j.get('company_name','')}" )
                          .lower(),
            "source": "Arbeitnow",
        })
    return jobs


# ── Source 2: RemoteOK (remote jobs worldwide) ───────────────
REMOTEOK_URL = "https://remoteok.com/api"


def fetch_remoteok():
    r = requests.get(REMOTEOK_URL, timeout=20)
    if r.status_code != 200:
        return []
    jobs = []
    data = r.json()
    if isinstance(data, list):
        data = data[1:]  # skip the meta row
    for j in data[:100]:
        jobs.append({
            "id": j.get("slug", j.get("url", "")),
            "title": j.get("position", j.get("title", "")),
            "company": j.get("company", "Unknown"),
            "location": j.get("location", "Remote"),
            "url": j.get("apply_url") or j.get("url", ""),
            "posted": datetime.fromtimestamp(j.get("epoch", 0), tz=timezone.utc).date().isoformat()
                      if j.get("epoch") else "",
            "haystack": f"{j.get('position','')} {' '.join(j.get('tags', []) or [])} "
                        f"{j.get('description','')}".lower(),
            "source": "RemoteOK",
        })
    return jobs


# ── Source 3: The Muse (US jobs) ─────────────────────────────
MUSE_URL = "https://www.themuse.com/api/public/jobs"


def fetch_muse():
    """Paginate a few pages; build individual job links from ids."""
    jobs = []
    for page in range(1, 4):
        try:
            r = requests.get(f"{MUSE_URL}?page={page}", timeout=20)
            if r.status_code != 200:
                break
            results = r.json().get("results", [])
            if not results:
                break
            for j in results:
                cats = [c.get("name", "") for c in (j.get("categories") or [])]
                tags = [t.get("name", "") for t in (j.get("tags") or [])]
                locs = [l.get("name", "") for l in (j.get("locations") or [])]
                jobs.append({
                    "id": str(j.get("id", "")),
                    "title": j.get("name", ""),
                    "company": (j.get("company") or {}).get("name", "Unknown"),
                    "location": ", ".join(locs) or "US",
                    "url": j.get("refs", {}).get("landing_page", ""),
                    "url": f"https://www.themuse.com/jobs/{j.get('company', {}).get('name', '').lower().replace(' ', '-').replace('.', '')}/{j.get('id')}",
                    "posted": (j.get("publication_date") or "")[:10],
                    "haystack": f"{j.get('name','')} {' '.join(cats)} {' '.join(tags)} "
                                f"{' '.join(locs)}".lower(),
                    "source": "The Muse",
                })
            time.sleep(0.3)
        except Exception:
            break
    return jobs


# ── Matching & Reporting ─────────────────────────────────────
def matches(haystack):
    return any(k in haystack for k in KEYWORDS)


def build_alert(job):
    posted = f" | 📅 Posted: {job['posted']}" if job.get("posted") else ""
    return (
        f"💼 <b>{job['title'].title()}</b>
"
        f"🏢 {job['company']}
"
        f"📍 {job['location']}{posted}
"
        f"🌐 {job['source']}
"
        f"🔗 <a href='{job['url']}'>Apply Here</a>"
    )


def main():
    print("Fetching real job listings...")
    all_jobs = []
    for fetch_fn in [fetch_arbeitnow, fetch_remoteok, fetch_muse]:
        try:
            all_jobs += fetch_fn()
        except Exception as e:
            print(f"{fetch_fn.__name__} failed: {e}")

    print(f"Fetched {len(all_jobs)} real job listings")
    seen = load_seen()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=FRESHNESS_DAYS)

    alerts = []
    for job in all_jobs:
        if not job.get("url") or not matches(job["haystack"]):
            continue
        posted = None
        try:
            if job.get("posted"):
                posted = datetime.strptime(job["posted"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc)
        except ValueError:
            posted = None
        # Already alerted once → skip (dedup).
        if job["url"] in seen:
            continue
        # Very old postings don't get alerts.
        if posted is not None and posted < cutoff:
            continue
        alerts.append(job)
        seen[job["url"]] = now.isoformat()

    save_seen(seen)

    # Chunked Telegram delivery (4096 char limit per message).
    period = "Morning" if datetime.now(timezone.utc).hour < 12 else "Evening"
    if alerts:
        header = (
            f"📋 <b>NEW JOB ALERTS — {period} Scan</b>
"
            f"📥 {len(alerts)} new match(es)
{'─' * 30}

"
        )
        chunks = []
        current = header
        for a in alerts[:12]:
            block = "
" + build_alert(a) + "
"
            if len(current) + len(block) > 3800:
                chunks.append(current)
                current = header
                current = header
            current += block
        if current:
            chunks.append(current)
        for chunk in chunks:
            send_telegram(chunk)
        print(f"Sent {len(alerts[:12])} alert(s) to Telegram")
    else:
        print("No new matching jobs this run. Nothing sent.")
        print(f"Tracking {len(seen)} seen job links total.")


if __name__ == "__main__":
    main()







































