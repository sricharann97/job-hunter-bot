import html, json, os, time, re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

# --- Config ---
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '')

# Keywords for matching
KEYWORDS = [
    'accounts executive', 'accounts assistant', 'junior accountant',
    'accountant trainee', 'tally operator', 'gst assistant', 'gst executive',
    'tds assistant', 'billing executive', 'finance assistant', 'bookkeeper',
    'back office finance', 'mis executive', 'accountant', 'tally', 'audit',
]

# Location filters
IN_KEYS = ['hyderabad', 'secunderabad', 'telangana', 'india']
EX_KEYS = [
    'remote', 'usa', 'us-', 'united states', 'uk-', 'united kingdom',
    'europe', 'dubai', 'uae', 'canada', 'australia', 'germany', 'wfh',
    'chennai', 'bangalore', 'bengaluru', 'mumbai', 'delhi', 'kolkata',
    'pune', 'kochi', 'coimbatore',
]

SEEN_FILE = 'seen_jobs.json'
TIMEOUT = 20
DAYS_BACK = 30

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept-Language': 'en-IN,en;q=0.9',
}

class JobBot:
    def __init__(self):
        self.seen_jobs = self.load_seen()
        self.new_jobs = []

    def load_seen(self):
        try:
            if os.path.exists(SEEN_FILE):
                with open(SEEN_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f).get('seen', {})
        except Exception as e:
            print(f"Error loading seen jobs: {e}")
        return {}

    def save_seen(self):
        now = datetime.now(timezone.utc)
        # Keep jobs from the last 60 days to prevent duplicates but keep file size manageable
        cutoff = (now - timedelta(days=60)).isoformat()
        cleaned_seen = {u: t for u, t in self.seen_jobs.items() if t > cutoff}
        
        try:
            tmp = SEEN_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({
                    'last_run_utc': now.isoformat(),
                    'seen': cleaned_seen
                }, f, indent=2)
            os.replace(tmp, SEEN_FILE)
        except Exception as e:
            print(f"Error saving seen jobs: {e}")

    def normalize(self, job):
        job['title'] = job.get('title', '').strip()
        job['company'] = job.get('company', 'Unknown').strip()
        job['location'] = job.get('location', 'Hyderabad').strip()
        job['url'] = job.get('url', '').strip()
        job['description'] = job.get('description', '').strip()
        job['salary'] = job.get('salary', '').strip()
        
        # Create a haystack for keyword matching
        job['haystack'] = f"{job['title']} {job['company']} {job['location']} {job['description']}".lower()
        
        # Create a unique key for deduplication beyond just URL
        # Normalized company + Normalized title
        clean_company = re.sub(r'[^a-z0-9]', '', job['company'].lower())
        clean_title = re.sub(r'[^a-z0-9]', '', job['title'].lower())
        job['dedupe_key'] = f"{clean_company}_{clean_title}"
        
        return job

    def is_match(self, job):
        # Check location
        h = ' ' + job['haystack'] + ' '
        if any(k in h for k in EX_KEYS):
            # Special case: 'india' is in IN_KEYS but we want to exclude other cities
            # Only allow if 'hyderabad' or 'secunderabad' is present
            if not any(k in h for k in ['hyderabad', 'secunderabad']):
                return False
        
        if not any(k in h for k in IN_KEYS):
            return False

        # Check keywords
        if not any(k in h for k in KEYWORDS):
            return False

        # Check if already seen (by URL or dedupe_key)
        if job['url'] in self.seen_jobs:
            return False
        
        # Check dedupe_key in seen values (we store ISO dates as values)
        # This is a bit slow but safer for re-posts
        if any(job['dedupe_key'] in k for k in self.seen_jobs.keys()):
            return False

        return True

    def safe_get(self, url, retries=3):
        for i in range(retries):
            try:
                r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                if r.status_code == 200:
                    return r
                if r.status_code == 403 and "not provide services in your region" in r.text:
                    return "REGION_BLOCKED"
                print(f"HTTP {r.status_code} for {url[:50]}")
            except Exception as e:
                print(f"Request error: {e}")
            time.sleep(2 * (i + 1))
        return None

    def fetch_linkedin(self):
        print("Fetching LinkedIn...")
        queries = ['accounts executive', 'junior accountant', 'tally gst']
        count = 0
        for q in queries:
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={quote_plus(q)}&location=Hyderabad%2C%20Telangana&f_TPR=r86400&start=0"
            r = self.safe_get(url)
            if not r or r == 'REGION_BLOCKED': continue
            
            soup = BeautifulSoup(r.text, 'html.parser')
            for card in soup.select('li'):
                try:
                    title_el = card.select_one('h3.base-search-card__title')
                    company_el = card.select_one('h4.base-search-card__subtitle')
                    link_el = card.select_one('a.base-card__full-link')
                    loc_el = card.select_one('span.job-search-card__location')
                    date_el = card.select_one('time')
                    
                    if not title_el or not link_el: continue
                    
                    url = link_el.get('href', '').split('?')[0]
                    job = self.normalize({
                        'title': title_el.get_text(strip=True),
                        'company': company_el.get_text(strip=True) if company_el else 'Unknown',
                        'location': loc_el.get_text(strip=True) if loc_el else 'Hyderabad',
                        'url': url,
                        'posted': date_el.get('datetime', '') if date_el else '',
                        'source': 'LinkedIn',
                        'description': card.get_text(" ", strip=True)
                    })
                    
                    if self.is_match(job):
                        self.new_jobs.append(job)
                        self.seen_jobs[job['url']] = datetime.now(timezone.utc).isoformat()
                        count += 1
                except Exception as e:
                    print(f"Error parsing LinkedIn card: {e}")
        print(f"LinkedIn: Found {count} new jobs.")

    def fetch_indeed(self):
        print("Fetching Indeed...")
        queries = ['accounts executive', 'junior accountant']
        count = 0
        for q in queries:
            url = f"https://in.indeed.com/jobs?q={quote_plus(q)}&l=Hyderabad%2C+Telangana&sort=date"
            r = self.safe_get(url)
            
            if r == 'REGION_BLOCKED':
                print("Indeed SKIP: Region blocked (runner IP).")
                return 
            
            if not r: continue
            
            import re
            m = re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]=(\{.+?\});', r.text)
            if m:
                try:
                    data = json.loads(m.group(1))
                    results = data["metaData"]["mosaicProviderJobCardsModel"]["results"]
                    for res in results:
                        jk = res.get("jobkey") or ""
                        job_url = f"https://in.indeed.com/viewjob?jk={jk}" if jk else res.get("link")
                        if not job_url: continue
                        
                        job = self.normalize({
                            'title': res.get("displayTitle") or res.get("title") or "",
                            'company': res.get("company") or "Unknown",
                            'location': res.get("formattedLocation") or "Hyderabad",
                            'url': job_url,
                            'salary': res.get("salarySnippet", {}).get("text", "") if isinstance(res.get("salarySnippet"), dict) else "",
                            'source': 'Indeed',
                            'description': res.get("snippet", "")
                        })
                        
                        if self.is_match(job):
                            self.new_jobs.append(job)
                            self.seen_jobs[job['url']] = datetime.now(timezone.utc).isoformat()
                            count += 1
                except Exception as e:
                    print(f"Indeed mosaic error: {e}")
            
            soup = BeautifulSoup(r.text, 'html.parser')
            for card in soup.select('div.job_seen_beacon'):
                try:
                    title_el = card.select_one('h2.jobTitle a')
                    if not title_el: continue
                    
                    jk = card.get('data-jk') or title_el.get('data-jk')
                    job_url = f"https://in.indeed.com/viewjob?jk={jk}" if jk else title_el.get('href')
                    if job_url and job_url.startswith('/'): job_url = "https://in.indeed.com" + job_url
                    
                    job = self.normalize({
                        'title': title_el.get_text(strip=True),
                        'company': card.select_one('.companyName').get_text(strip=True) if card.select_one('.companyName') else 'Unknown',
                        'location': card.select_one('.companyLocation').get_text(strip=True) if card.select_one('.companyLocation') else 'Hyderabad',
                        'url': job_url,
                        'source': 'Indeed',
                        'description': card.select_one('.job-snippet').get_text(strip=True) if card.select_one('.job-snippet') else ''
                    })
                    
                    if self.is_match(job):
                        self.new_jobs.append(job)
                        self.seen_jobs[job['url']] = datetime.now(timezone.utc).isoformat()
                        count += 1
                except Exception as e:
                    pass
        print(f"Indeed: Found {count} new jobs.")

    def send_telegram(self):
        if not self.new_jobs:
            print("No new jobs to alert.")
            return

        print(f"Sending {len(self.new_jobs)} alerts to Telegram...")
        self.new_jobs.sort(key=lambda x: x['source'])
        
        message = f"📋 <b>NEW JOB ALERTS (Hyderabad)</b>\n"
        message += f"Found {len(self.new_jobs)} new matching roles.\n\n"
        
        for i, job in enumerate(self.new_jobs[:15]):
            job_str = (f"💼 <b>{html.escape(job['title'])}</b>\n"
                       f"🏢 {html.escape(job['company'])}\n"
                       f"📍 {html.escape(job['location'])}\n")
            if job['salary']:
                job_str += f"💰 {html.escape(job['salary'])}\n"
            job_str += (f"🌐 {job['source']}\n"
                        f"🔗 <a href='{job['url']}'>View & Apply</a>\n\n")
            
            if len(message) + len(job_str) > 4000:
                self._post_to_telegram(message)
                message = "📋 <b>NEW JOB ALERTS (Cont.)</b>\n\n"
            
            message += job_str
            
        if message:
            self._post_to_telegram(message)
            
        if len(self.new_jobs) > 15:
            self._post_to_telegram(f"<i>...and {len(self.new_jobs) - 15} more roles found. Check the tracker for full list.</i>")

    def _post_to_telegram(self, text):
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            'chat_id': CHAT,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        try:
            r = requests.post(url, json=payload, timeout=TIMEOUT)
            if r.status_code != 200:
                print(f"Telegram error: {r.text}")
        except Exception as e:
            print(f"Telegram request failed: {e}")

    def run(self):
        self.fetch_linkedin()
        self.fetch_indeed()
        self.send_telegram()
        self.save_seen()

if __name__ == "__main__":
    if not TOKEN or not CHAT:
        print("Error: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set.")
    else:
        bot = JobBot()
        bot.run()
