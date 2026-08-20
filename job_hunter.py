import html

import json

import os

import time

from datetime import datetime, timezone, timedelta

from urllib.parse import quote_plus



import requests

from bs4 import BeautifulSoup



# Telegram Config

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]



# Candidate search keywords

KEYWORDS = [
    
    "accounts executive", "accounts assistant", "junior accountant",
    
    "accountant trainee", "tally operator", "gst assistant",
    
    "gst executive", "tds assistant", "billing executive",
    
    "finance assistant", "bookkeeper", "back office finance",
    
    "mis executive", "accountant", "finance", "accounting",
    
    "tally", "audit", "clerk", "data entry", "admin",
    
]



SEEN_FILE = "seen_jobs.json"

FRESHNESS_DAYS = 30

TIMEOUT = 20

HEADERS = {
    
    "User-Agent": (
        
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        
        "Chrome/124.0 Safari/537.36"
        
    ),
    
    "Accept-Language": "en-IN,en;q=0.9",
    
}





def load_seen():
    
    if os.path.exists(SEEN_FILE):
        
        try:
            
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                
                return json.load(f).get("seen", {})
                
        except (OSError, ValueError):
            
            print("Could not read seen_jobs.json; starting with an empty tracker.")
            
    return {}
    




def save_seen(seen):
    
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    
    trimmed = {u: t for u, t in seen.items() if t > cutoff}
    
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        
        json.dump(
            
            {"last_run_utc": datetime.now(timezone.utc).isoformat(), "seen": trimmed},
            
            f,
            
            indent=2,
            
        )
        




def send_telegram(message):
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    payload = {
        
        "chat_id": TELEGRAM_CHAT_ID,
        
        "text": message,
        
        "parse_mode": "HTML",
        
        "disable_web_page_preview": False,
        
    }
    
    try:
        
        response = requests.post(url, json=payload, timeout=15)
        
        print(f"Telegram HTTP {response.status_code}")
        
        if response.status_code != 200:
            
            print(response.text[:300])
            
    except Exception as exc:
        
        print(f"Telegram send failed: {exc}")
        




def normalise_job(job):
    
    job["title"] = job.get("title", "").strip()
    
    job["company"] = job.get("company", "Unknown").strip()
    
    job["location"] = job.get("location", "Not specified").strip()
    
    job["url"] = job.get("url", "").strip()
    
    job["haystack"] = job.get(
        
        "haystack", f"{job['title']} {job['company']} {job['location']}"
        
    ).lower()
    
    return job
    




def fetch_arbeitnow():
    
    response = requests.get(
        
        "https://www.arbeitnow.com/api/job-board-api", timeout=TIMEOUT
        
    )
    
    response.raise_for_status()
    
    jobs = []
    
    for item in response.json().get("data", [])[:200]:
        
        jobs.append(normalise_job({
            
            "id": item.get("slug", item.get("url", "")),
            
            "title": item.get("title", ""),
            
            "company": item.get("company_name", "Unknown"),
            
            "location": item.get("location", "Not specified"),
            
            "url": item.get("url", ""),
            
            "posted": (item.get("date") or "")[:10],
            
            "haystack": f"{item.get('title', '')} {item.get('description', '')} "
            
                        f"{item.get('company_name', '')}",
            
            "source": "Arbeitnow",
            
        }))
        
    return jobs
    




def fetch_remoteok():
    
    response = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=TIMEOUT)
    
    if response.status_code != 200:
        
        return []
        
    data = response.json()
    
    if isinstance(data, list):
        
        data = data[1:]
        
    jobs = []
    
    for 
















































































