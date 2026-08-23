import html, json, os, time, re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup
from dataclasses import asdict, dataclass
from typing import Any

# --- Config ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT  = os.environ.get('TELEGRAM_CHAT_ID')

# Job Search Config
KEYWORDS = [
    'accounts executive', 'accounts assistant', 'junior accountant',
    'accountant trainee', 'tally operator', 'gst assistant', 'gst executive',
    'tds assistant', 'billing executive', 'finance assistant', 'bookkeeper',
    'back office finance', 'mis executive', 'accountant', 'tally', 'audit',
]

SEEN    = 'seen_jobs.json'
TIMEOUT = 20
DAYS    = 30

HEAD = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-IN,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
}

IN_KEYS = [
    'hyderabad', 'secunderabad', 'telangana',
    'warangal', 'karimnagar', 'nizamabad', 'mahbubnagar',
    'medak', 'nalgonda', 'khammam', 'india',
]
EX_KEYS = [
    'remote', 'usa', 'us-', 'united states', 'uk-', 'united kingdom',
    'europe', 'dubai', 'uae', 'canada', 'australia', 'germany', 'wfh',
    'chennai', 'bangalore', 'bengaluru', 'mumbai', 'delhi', 'kolkata',
    'pune', 'kochi', 'coimbatore',
]

# --- Scoring Logic ---
@dataclass(frozen=True)
class CandidateProfile:
    target_roles: list[str]
    skills: list[str]
    preferred_locations: list[str]
    minimum_experience_years: float | None = None

@dataclass(frozen=True)
class Job:
    title: str
    description: str
    location: str = ""
    posted_at: str | None = None
    url: str | None = None

@dataclass(frozen=True)
class ScoreComponent:
    name: str
    points: float
    max_points: float
    explanation: str
    evidence: list[str]

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()

def find_phrase_matches(haystack: str, phrases: list[str]) -> list[str]:
    normalized = normalize(haystack)
    matches: list[str] = []
    for phrase in phrases:
        cleaned = normalize(phrase)
        if cleaned and re.search(rf"(?<!\w){re.escape(cleaned)}(?!\w)", normalized):
            matches.append(phrase)
    return matches

def score_job(job: Job, profile: CandidateProfile) -> dict[str, Any]:
    components = []
    
    # Role Match (30 points)
    role_matches = find_phrase_matches(job.title, profile.target_roles)
    role_points = 30.0 if role_matches else 0.0
    components.append(ScoreComponent("role_match", role_points, 30.0, 
        "Title matches target role" if role_matches else "Title mismatch", role_matches))
    
    # Skill Match (35 points)
    skill_matches = find_phrase_matches(f"{job.title}\n{job.description}", profile.skills)
    coverage = len(skill_matches) / len(profile.skills) if profile.skills else 0.0
    skill_points = round(35.0 * coverage, 1)
    components.append(ScoreComponent("skill_match", skill_points, 35.0, 
        f"Matched {len(skill_matches)} skills", skill_matches))
    
    # Location Match (15 points)
    loc_matches = find_phrase_matches(job.location, profile.preferred_locations)
    remote_match = "remote" in normalize(job.location) or "hybrid" in normalize(job.location)
    loc_points = 15.0 if loc_matches else 10.0 if remote_match else 0.0
    components.append(ScoreComponent("location_match", loc_points, 15.0, 
        "Location match" if loc_matches else "Remote/Hybrid" if remote_match else "Location mismatch", loc_matches or [job.location]))
    
    # Experience Match (10 points)
    exp_years = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", normalize(job.description))]
    required_years = min(exp_years) if exp_years else 0
    # profile.minimum_experience_years is 0 for fresher
    exp_points = 10.0 if (profile.minimum_experience_years or 0) >= required_years else 5.0 if not exp_years else 0.0
    components.append(ScoreComponent("experience_match", exp_points, 10.0, 
        "Experience met" if exp_points == 10.0 else "Review needed" if exp_points == 5.0 else "Experience gap", [f"Required: {required_years}, Have: {profile.minimum_experience_years}"]))
    
    # Freshness (10 points)
    fresh_points = 10.0 
    components.append(ScoreComponent("freshness", fresh_points, 10.0, "New listing", []))
    
    total = round(sum(c.points for c in components), 1)
    decision = "high_priority_review" if total >= 75 else "review" if total >= 50 else "low_priority"
    
    return {
        "score": total,
        "decision": decision,
        "components": [asdict(c) for c in components]
    }

# --- Scraping Functions ---
def is_hyd(j):
    h = ' ' + j.get('haystack', '') + ' '
    if any(k in h for k in EX_KEYS):
        return False
    return any(k in h for k in IN_KEYS)

def norm(j):
    j['title']    = j.get('title', '').strip()
    j['company']  = j.get('company', 'Unknown').strip()
    j['location'] = j.get('location', 'Not specified').strip()
    j['url']      = j.get('url', '').strip()
    j['haystack'] = j.get('haystack', f"{j['title']} {j['company']} {j['location']}").lower()
    return j

def unique(js):
    d = {}
    for j in js:
        k = j.get('url') or j.get('id')
        if k:
            d.setdefault(k, j)
    return list(d.values())

def safe_get(url, retries=3, delay=5):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEAD, timeout=TIMEOUT)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 999):
                time.sleep(delay * (attempt + 1))
        except requests.RequestException:
            time.sleep(delay)
    return None

def fetch_linkedin():
    out = []
    for q in ['accounts executive tally', 'junior accountant fresher', 'gst finance fresher']:
        u = ('https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords='
             + quote_plus(q) + '&location=Hyderabad%2C%20Telangana&f_TPR=r86400&start=0')
        r = safe_get(u)
        if not r: continue
        s = BeautifulSoup(r.text, 'html.parser')
        for c in s.select('li'):
            t = c.select_one('h3.base-search-card__title')
            a = c.select_one('a.base-card__full-link')
            if not t or not a: continue
            co = c.select_one('h4.base-search-card__subtitle')
            lo = c.select_one('span.job-search-card__location')
            url = a.get('href', '').split('?')[0]
            out.append(norm({
                'id': url,
                'title': t.get_text(' ', strip=True),
                'company': co.get_text(' ', strip=True) if co else 'Unknown',
                'location': lo.get_text(' ', strip=True) if lo else 'Hyderabad',
                'url': url,
                'source': 'LinkedIn',
                'haystack': c.get_text(' ', strip=True)
            }))
    return unique(out)

def fetch_internshala():
    out = []
    u = 'https://internshala.com/jobs/accounting-jobs-in-hyderabad/'
    r = safe_get(u)
    if not r: return []
    s = BeautifulSoup(r.text, 'html.parser')
    for c in s.select('div.individual_internship'):
        t = c.select_one('h3.job-internship-name a') or c.select_one('.profile a')
        co = c.select_one('.company-name a') or c.select_one('.company_name a')
        lo = c.select_one('.location_names') or c.select_one('.location_link')
        if not t: continue
        url = urljoin(u, t.get('href', ''))
        out.append(norm({
            'id': url,
            'title': t.get_text(' ', strip=True),
            'company': co.get_text(' ', strip=True) if co else 'Unknown',
            'location': lo.get_text(' ', strip=True) if lo else 'Hyderabad',
            'url': url,
            'source': 'Internshala',
            'haystack': c.get_text(' ', strip=True)
        }))
    return out

def fetch_shine():
    out = []
    u = 'https://www.shine.com/job-search/accounting-jobs-in-hyderabad?q=accounting&l=hyderabad'
    r = safe_get(u)
    if not r: return []
    s = BeautifulSoup(r.text, 'html.parser')
    for c in s.select('.jobCard, [itemtype="http://schema.org/JobPosting"]'):
        t = c.select_one('h2 a') or c.select_one('h2[itemprop="name"] a')
        co = c.select_one('.jobCard_jobCard_cName__mYnIm') or c.select_one('div.jobCard_jobCard_cName__mYnIm span')
        lo = c.select_one('.jobCard_locationIcon__s_Kk_') or c.select_one('div.jobCard_locationIcon__s_Kk_')
        if not t: continue
        url = urljoin(u, t.get('href', ''))
        out.append(norm({
            'id': url,
            'title': t.get_text(' ', strip=True),
            'company': co.get_text(' ', strip=True) if co else 'Unknown',
            'location': lo.get_text(' ', strip=True) if lo else 'Hyderabad',
            'url': url,
            'source': 'Shine',
            'haystack': c.get_text(' ', strip=True)
        }))
    return out

def send(m):
    if not TOKEN or not CHAT: return
    try:
        requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',
                      json={'chat_id': CHAT, 'text': m, 'parse_mode': 'HTML'}, timeout=15)
    except: pass

def check_maintenance():
    # SGT = UTC + 8
    now_utc = datetime.now(timezone.utc)
    maint_start = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc) # 8:00 AM SGT
    maint_end = datetime(2026, 8, 24, 23, 59, tzinfo=timezone.utc) # 7:59 AM SGT on 25th is roughly midnight UTC on 24th
    
    if maint_start <= now_utc <= maint_end:
        msg = ("⚠️ <b>MANUS MAINTENANCE ALERT</b>\n\n"
               "The Manus platform is currently undergoing scheduled updates (Aug 23 - Aug 25).\n\n"
               "🔹 <b>Status:</b> Manus Web/App likely offline.\n"
               "🔹 <b>Your Bot:</b> GitHub automation is ACTIVE and running normally.\n"
               "🔹 <b>Interview:</b> Maple Tax Consulting tomorrow at 2:00 PM IST.\n\n"
               "<i>I will continue to send you job alerts every 3 hours as usual.</i>")
        send(msg)

def main():
    # Check for maintenance first
    check_maintenance()
    
    try:
        with open('profile.json', 'r') as f:
            profile_data = json.load(f)
            profile = CandidateProfile(**profile_data)
    except Exception as e:
        print(f"Error loading profile.json: {e}")
        return

    # 1. Scrape Jobs
    allj = []
    for f in [fetch_linkedin, fetch_internshala, fetch_shine]:
        try: 
            jobs = f()
            print(f"Fetched {len(jobs)} from {f.__name__}")
            allj += jobs
        except Exception as e:
            print(f"Error in {f.__name__}: {e}")
    allj = unique(allj)
    print(f"Total unique jobs found: {len(allj)}")
    
    # 2. Filter & Score
    seen_data = {'last_run_utc': '', 'seen': {}}
    if os.path.exists(SEEN):
        try:
            with open(SEEN, 'r') as f:
                seen_data = json.load(f)
        except: pass
    
    seen = seen_data.get('seen', {})
    scored_jobs = []
    for j in allj:
        if not j.get('url') or j['url'] in seen: continue
        if not is_hyd(j): continue
        
        job_obj = Job(title=j['title'], description=j.get('haystack', ''), location=j['location'], url=j['url'])
        res = score_job(job_obj, profile)
        j.update(res)
        
        if j['score'] >= 50:
            scored_jobs.append(j)
            seen[j['url']] = datetime.now(timezone.utc).isoformat()

    # 3. Final Telegram Report
    if scored_jobs:
        scored_jobs.sort(key=lambda x: x['score'], reverse=True)
        msg = f"📋 <b>JOB ALERT REPORT ({len(scored_jobs)})</b>\n"
        msg += f"<i>Hyderabad Accounting - Scored & Filtered</i>\n\n"
        for j in scored_jobs[:10]:
            msg += f"⭐ <b>{j['score']}</b> | <b>{j['title']}</b>\n🏢 {j['company']} ({j['source']})\n🔗 <a href='{j['url']}'>View Job</a>\n\n"
        send(msg)
        print(f"Sent alert for {len(scored_jobs)} jobs.")
    else:
        print("No new matching jobs found.")

    seen_data['last_run_utc'] = datetime.now(timezone.utc).isoformat()
    seen_data['seen'] = seen
    with open(SEEN, 'w') as f:
        json.dump(seen_data, f, indent=2)

if __name__ == '__main__':
    main()
