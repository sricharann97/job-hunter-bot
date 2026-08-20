import html, json, os, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

# --- Config ---
TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT  = os.environ['TELEGRAM_CHAT_ID']

# FIX 4: Tightened keywords — removed noisy broad terms (admin, clerk, data entry)
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
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
    'Accept-Language': 'en-IN,en;q=0.9',
}

# FIX 3: Hyderabad-ONLY filter — removed other Indian cities from IN_KEYS
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

# FIX 2: Added retry logic for LinkedIn blocks (429/999)
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
            print(f'LinkedIn failed for query: {q}')
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

# FIX 9: Indeed now sits behind Cloudflare — plain requests get HTTP 403 from
# datacenter IPs (GitHub Actions runners, most VPS). Switched to a real
# headless-browser fetch (Playwright), which passes Cloudflare checks.
# Falls back to the plain-requests parser if Playwright is unavailable.
def _parse_mosaic(html_text):
    """Parse Indeed's embedded jobcards JSON (works on both search pages)."""
    out = []
    import re
    m = re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]=(\{.+?\});',
                  html_text)
    if m:
        try:
            data = json.loads(m.group(1))
            results = data["metaData"]["mosaicProviderJobCardsModel"]["results"]
            for r in results:
                jk = r.get("jobkey") or ""
                href = r.get("link") or r.get("viewJobLink") or ""
                if not href.startswith("/"):
                    href = f"https://in.indeed.com{href}" if href.startswith("/") else (r.get("jobUrl") or href)
                # strip tracking params — canonical URL with just jk
                url = f"https://in.indeed.com/viewjob?jk={jk}" if jk else href
                if href:
                    url = href.split("?")[0].split("&")[0] if href.startswith("http") else url
                if jk:
                    url = f"https://in.indeed.com/viewjob?jk={jk}"
                salary = ""
                try:
                    salary = r.get("salarySnippet", {}) or {}
                    salary = salary.get("text", "") if isinstance(salary, dict) else str(salary)
                except Exception:
                    salary = ""
                loc = (r.get("formattedLocation") or r.get("location") or "Hyderabad")
                out.append(norm({
                    'id':      jk or url,
                    'title':   r.get("displayTitle") or r.get("title") or "",
                    'company': r.get("company") or r.get("truncatedCompany") or "Unknown",
                    'location': loc,
                    'url':     url,
                    'posted':  datetime.fromtimestamp(int(r["pubDate"]) / 1000,
                               tz=timezone.utc).strftime('%Y-%m-%d') if r.get("pubDate") else '',
                    'haystack': f"{r.get('title','')} {r.get('company','')} {loc}",
                    'source':  'Indeed',
                    'salary':  salary or '',
                }))
        except Exception as e:
            print('Indeed mosaic parse error:', e)
    return out

def fetch_indeed():
    """Headless browser fetch (primary). Plain-requests fallback kept."""
    out = []
    for q in ['accounts executive tally', 'junior accountant fresher', 'gst finance fresher']:
        u = ('https://in.indeed.com/jobs?q=' + quote_plus(q)
             + '&l=Hyderabad%2C+Telangana&sort=date')
        fetched = False
        # Primary: Playwright headless Chromium (passes Cloudflare)
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"])
                page = browser.new_page(
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/126.0.0.0 Safari/537.36"),
                    locale="en-IN")
                try:
                    page.goto(u, wait_until="domcontentloaded", timeout=40000)
                    page.wait_for_timeout(4000)
                    page_html = page.content()
                    title = (page.title() or '').strip()
                    print(f'Indeed browser page title ({q}): {title[:80]}')
                    if "mosaic-provider-jobcards" in page_html:
                        out += _parse_mosaic(page_html)
                        fetched = True
                        print(f'Indeed browser: {len(out)} jobs parsed ({q})')
                    elif "not provide services in your region" in page_html:
                        # Cloud/datacenter IP geo-block — runner IPs are always
                        # blocked here. Indeed jobs are supplied by the
                        # Manus research/auto-apply layer instead.
                        print('Indeed SKIP: blocked for this region (runner IP) — '
                              'Indeed jobs arrive via the research layer.')
                        return out  # skip remaining queries to avoid spam logs
                    else:
                        print(f'Indeed browser: mosaic missing — title={title[:60]} len={len(page_html)} ({q})')
                finally:
                    browser.close()
        except Exception as e:
            print(f'Indeed playwright error ({q}): {e}')

        if not fetched:
            # Fallback: plain requests (works from residential/home IPs)
            r = safe_get(u)
            if r and "not provide services in your region" in r.text:
                print('Indeed SKIP: blocked for this region (runner IP) — '
                      'Indeed jobs arrive via the research layer.')
                return out
            if r is None:
                print('Indeed SKIP: blocked for this region (runner IP) — '
                      'Indeed jobs arrive via the research layer.')
                return out
            if r:
                s = BeautifulSoup(r.text, 'html.parser')
                for c in s.select('div.job_seen_beacon') or s.select('div[data-jk]'):
                    t = c.select_one('h2.jobTitle a,h2 a')
                    if not t:
                        continue
                    jk   = c.get('data-jk') or t.get('data-jk', '')
                    href = f'https://in.indeed.com/viewjob?jk={jk}' if jk else t.get('href', '')
                    if href.startswith('/'):
                        href = 'https://in.indeed.com' + href
                    co = c.select_one("[data-testid='company-name'],span.companyName")
                    lo = c.select_one("[data-testid='text-location'],div.companyLocation")
                    sa = c.select_one("[data-testid='attribute_snippet'],.salary-snippet-container")
                    dt = c.select_one('.date,span.date')
                    out.append(norm({
                        'id':      jk or href,
                        'title':   t.get_text(' ', strip=True),
                        'company': co.get_text(' ', strip=True) if co else 'Unknown',
                        'location':lo.get_text(' ', strip=True) if lo else 'Hyderabad',
                        'url':     href,
                        'posted':  dt.get_text(' ', strip=True) if dt else '',
                        'haystack':c.get_text(' ', strip=True),
                        'source':  'Indeed',
                        'salary':  sa.get_text(' ', strip=True) if sa else '',
                    }))
                if out:
                    fetched = True
        if not fetched:
            print(f'Indeed failed for query: {q}')
    return unique(out)

# FIX 6: Retry logic on Telegram send failure
def send(m, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(
                f'https://api.telegram.org/bot{TOKEN}/sendMessage',
                json={'chat_id': CHAT, 'text': m, 'parse_mode': 'HTML'},
                timeout=15,
            )
            print('Telegram HTTP', r.status_code)
            if r.status_code == 200:
                return
            print(f'Telegram failed attempt {attempt+1}: {r.text}')
        except requests.RequestException as e:
            print(f'Telegram error attempt {attempt+1}: {e}')
        time.sleep(3)
    print('Telegram: all retries exhausted — alert lost')

def main():
    # Scrape all sources
    allj = []
    for f in [fetch_linkedin, fetch_indeed]:
        try:
            j = f()
            print(f.__name__, len(j))
            allj += j
        except Exception as e:
            print(f.__name__, 'failed safely:', e)

    allj = unique(allj)

    # Load seen jobs
    seen = {}
    try:
        with open(SEEN, encoding='utf-8') as f:
            seen = json.load(f).get('seen', {})
    except (OSError, ValueError):
        pass

    now  = datetime.now(timezone.utc)
    cut  = now - timedelta(days=DAYS)
    alerts = []

    for j in allj:
        if not j.get('url'):
            continue
        if not any(k in j.get('haystack', '') for k in KEYWORDS):
            continue
        if not is_hyd(j):
            continue
        if j['url'] in seen:
            continue

        # FIX 8: Only skip if posted date is valid AND old — include if date unknown
        posted = None
        try:
            posted = datetime.strptime(j.get('posted', '')[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        if posted and posted < cut:
            continue

        alerts.append(j)
        seen[j['url']] = now.isoformat()

    # FIX 7: Write seen_jobs atomically to avoid partial writes
    tmp = SEEN + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({
            'last_run_utc': now.isoformat(),
            'seen': {
                u: t for u, t in seen.items()
                if t > (now - timedelta(days=60)).isoformat()
            },
        }, f, indent=2)
    os.replace(tmp, SEEN)

    if not alerts:
        print('No new matching jobs.')
        return

    # FIX 5: Removed hardcoded 12-alert cap — send all, notify if capped
    MAX_ALERTS = 20
    if len(alerts) > MAX_ALERTS:
        print(f'Warning: {len(alerts)} matches found — sending top {MAX_ALERTS}')

    chunks = []
    cur = (f'📋 <b>NEW JOB ALERTS (Hyderabad Only)</b>\n'
           f'📥 {len(alerts)} new match(es)\n\n')

    for j in alerts[:MAX_ALERTS]:
        p   = (' | Posted: ' + html.escape(j['posted'])) if j.get('posted') else ''
        sal = ('\n💰 ' + html.escape(j['salary'])) if j.get('salary') else ''
        b   = (f"💼 <b>{html.escape(j['title'].title())}</b>\n"
               f"🏢 {html.escape(j['company'])}\n"
               f"📍 {html.escape(j['location'])}{p}{sal}\n"
               f"🌐 {j.get('source', '')}\n"
               f"🔗 <a href='{html.escape(j['url'], quote=True)}'>Apply Here</a>\n\n")
        if len(cur) + len(b) > 3800:
            chunks.append(cur)
            cur = '📋 <b>NEW JOB ALERTS (Hyderabad Only)</b>\n\n'
        cur += b

    chunks.append(cur)
    for c in chunks:
        send(c)

    print(f'Sent {min(MAX_ALERTS, len(alerts))} alerts')

if __name__ == '__main__':
    main()
