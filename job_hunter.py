import html, json, os, time, subprocess
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

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

# Database Config
NOTION_DB_URL = "collection://6bfb694d-4c86-4bde-b09a-56f25b0b1250"
SHEET_ID = "1msxG0oXEsO_JSZJbC-QicRQBPEhNe0WF5hLMmVuK-sI"

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
            print(f'HTTP {r.status_code} on attempt {attempt+1} — URL: {url[:80]}')
            if r.status_code in (429, 999):
                time.sleep(delay * (attempt + 1))
        except requests.RequestException as e:
            print(f'Request error attempt {attempt+1}: {e}')
            time.sleep(delay)
    return None

def fetch_linkedin():
    out = []
    for q in ['accounts executive tally', 'junior accountant fresher', 'gst finance fresher']:
        u = ('https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords='
             + quote_plus(q) + '&location=Hyderabad%2C%20Telangana&f_TPR=r86400&start=0')
        r = safe_get(u)
        if not r:
            continue
        s = BeautifulSoup(r.text, 'html.parser')
        for c in s.select('li'):
            t  = c.select_one('h3.base-search-card__title')
            a  = c.select_one('a.base-card__full-link')
            if not t or not a:
                continue
            co  = c.select_one('h4.base-search-card__subtitle')
            lo  = c.select_one('span.job-search-card__location')
            dt  = c.select_one('time')
            url = a.get('href', '').split('?')[0]
            out.append(norm({
                'id':      c.get('data-entity-urn') or url,
                'title':   t.get_text(' ', strip=True),
                'company': co.get_text(' ', strip=True) if co else 'Unknown',
                'location':lo.get_text(' ', strip=True) if lo else 'Hyderabad',
                'url':     url,
                'posted':  dt.get('datetime', '')[:10] if dt else '',
                'haystack':c.get_text(' ', strip=True),
                'source':  'LinkedIn',
            }))
    return unique(out)

def fetch_internshala():
    out = []
    u = 'https://internshala.com/jobs/accounting-jobs-in-hyderabad/'
    r = safe_get(u)
    if not r:
        return []
    s = BeautifulSoup(r.text, 'html.parser')
    for c in s.select('div.individual_internship'):
        t = c.select_one('h3.job-internship-name a') or c.select_one('.profile a')
        co = c.select_one('.company-name a') or c.select_one('.company_name a')
        lo = c.select_one('.location_names') or c.select_one('.location_link')
        if not t:
            continue
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
    if not r:
        return []
    s = BeautifulSoup(r.text, 'html.parser')
    # Shine uses different classes for their job cards
    for c in s.select('.jobCard, [itemtype="http://schema.org/JobPosting"]'):
        t = c.select_one('h2 a') or c.select_one('h2[itemprop="name"] a')
        co = c.select_one('.jobCard_jobCard_cName__mYnIm') or c.select_one('div.jobCard_jobCard_cName__mYnIm span')
        lo = c.select_one('.jobCard_locationIcon__s_Kk_') or c.select_one('div.jobCard_locationIcon__s_Kk_')
        if not t:
            continue
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

def fetch_naukri():
    # Naukri usually requires JS, but we can try to extract from the static search page
    # or rely on the user's Gmail alerts which are already monitored.
    # For now, we'll keep it as a placeholder that logs the attempt.
    print("Naukri scraping is limited; relying on Gmail alerts for Naukri jobs.")
    return []

def fetch_indeed():
    # Indeed is geo-blocked on datacenter IPs.
    return []

def run_mcp(server, tool, input_data):
    """Helper to run MCP tools via CLI."""
    try:
        cmd = [
            'manus-mcp-cli', 'tool', 'call', tool,
            '--server', server,
            '--input', json.dumps(input_data)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            for line in reversed(lines):
                if line.startswith('{') or line.startswith('['):
                    return json.loads(line)
        return None
    except Exception as e:
        print(f"MCP Error ({tool}): {e}")
        return None

def monitor_gmail():
    """Scan Gmail for job-related updates."""
    if not os.path.exists('/usr/bin/manus-mcp-cli'):
        return []
    
    print("Monitoring Gmail...")
    query = "after:2026/08/20 (interview OR offer OR application OR recruiter OR hiring OR 'job alert')"
    results = run_mcp('gmail', 'gmail_search_messages', {"query": query})
    if not results or 'messages' not in results:
        return []
    
    updates = []
    for msg in results['messages'][:10]:
        details = run_mcp('gmail', 'gmail_get_message', {"id": msg['id']})
        if details:
            updates.append({
                'subject': details.get('subject', 'No Subject'),
                'from': details.get('from', 'Unknown'),
                'snippet': details.get('snippet', ''),
                'date': details.get('date', '')
            })
    return updates

def sync_database(jobs, updates):
    """Sync new jobs and email updates to Notion and Google Sheets."""
    if not os.path.exists('/usr/bin/manus-mcp-cli'):
        return
    
    print(f"Syncing {len(jobs)} jobs to Notion...")
    for j in jobs:
        props = {
            "Job Title": j['title'],
            "Company": j['company'],
            "Location": j['location'],
            "URL": j['url'],
            "Status": "Not started",
            "date:Date Found:start": datetime.now().strftime('%Y-%m-%d')
        }
        run_mcp('notion', 'notion-create-page', {
            "parent_data_source_url": NOTION_DB_URL,
            "properties": props
        })

    if jobs:
        print("Updating Google Sheets...")
        rows = [[datetime.now().strftime('%Y-%m-%d'), j['title'], j['company'], j['location'], j['source'], "No", j['url'], "Not started", ""] for j in jobs]
        body = {"values": rows}
        subprocess.run(['gws', 'sheets', '+append', SHEET_ID, 'Applications!A:I', '--input', json.dumps(body)])

def send(m, retries=3):
    if not TOKEN or not CHAT:
        print("Telegram config missing, skipping alert.")
        return
    for attempt in range(retries):
        try:
            r = requests.post(
                f'https://api.telegram.org/bot{TOKEN}/sendMessage',
                json={'chat_id': CHAT, 'text': m, 'parse_mode': 'HTML'},
                timeout=15,
            )
            if r.status_code == 200:
                return
            print(f'Telegram failed attempt {attempt+1}: {r.text}')
        except requests.RequestException as e:
            print(f'Telegram error attempt {attempt+1}: {e}')
        time.sleep(3)

def main():
    # 1. Scrape Jobs
    allj = []
    sources = [fetch_linkedin, fetch_internshala, fetch_shine, fetch_naukri, fetch_indeed]
    for f in sources:
        try:
            j = f()
            print(f"{f.__name__}: found {len(j)} jobs")
            allj += j
        except Exception as e:
            print(f"{f.__name__} failed safely: {e}")

    allj = unique(allj)

    # 2. Filter & Deduplicate
    seen = {}
    try:
        with open(SEEN, encoding='utf-8') as f:
            seen = json.load(f).get('seen', {})
    except (OSError, ValueError):
        pass

    now = datetime.now(timezone.utc)
    cut = now - timedelta(days=DAYS)
    
    # Clean up old seen jobs
    seen = {k: v for k, v in seen.items() if datetime.fromisoformat(v) > cut}

    alerts = []
    for j in allj:
        if not j.get('url') or j['url'] in seen:
            continue
        # Check keywords in title or haystack
        if not any(k in j.get('haystack', '') for k in KEYWORDS):
            continue
        if not is_hyd(j):
            continue
        
        alerts.append(j)
        seen[j['url']] = now.isoformat()

    # 3. Monitor Gmail
    email_updates = monitor_gmail()
    if email_updates:
        msg = "📧 <b>New Email Updates</b>\n\n"
        for u in email_updates:
            msg += f"From: {u['from']}\nSub: {u['subject']}\n\n"
        send(msg)

    # 4. Sync Database
    if alerts:
        sync_database(alerts, email_updates)

    # 5. Save State
    with open(SEEN, 'w', encoding='utf-8') as f:
        json.dump({'last_run_utc': now.isoformat(), 'seen': seen}, f, indent=2)

    # 6. Send Alerts
    if alerts:
        msg = f"📋 <b>DAILY JOB REPORT ({len(alerts)})</b>\n"
        msg += f"<i>Sources: LinkedIn, Internshala, Shine, Gmail</i>\n\n"
        for j in alerts[:15]: # Show top 15
            msg += f"💼 <b>{j['title']}</b>\n🏢 {j['company']} ({j['source']})\n🔗 <a href='{j['url']}'>Apply</a>\n\n"
        
        if len(alerts) > 15:
            msg += f"...and {len(alerts)-15} more jobs added to your tracker."
            
        send(msg)
    else:
        # Send a heartbeat if no jobs found but Gmail was checked
        send("✅ <b>System Check</b>: Job search complete. No new matches found in the last 3 hours.")

if __name__ == '__main__':
    main()
