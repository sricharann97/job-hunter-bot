import html,json,os,time

from datetime import datetime,timezone,timedelta

from urllib.parse import quote_plus

import requests

from bs4 import BeautifulSoup

TOKEN=os.environ['TELEGRAM_TOKEN']; CHAT=os.environ['TELEGRAM_CHAT_ID']

KEYWORDS=['accounts executive','accounts assistant','junior accountant','accountant trainee','tally operator','gst assistant','gst executive','tds assistant','billing executive','finance assistant','bookkeeper','back office finance','mis executive','accountant','finance','accounting','tally','audit','clerk','data entry','admin']

SEEN='seen_jobs.json'; TIMEOUT=20; DAYS=30

HEAD={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36','Accept-Language':'en-IN,en;q=0.9'}
# Hyderabad-India-only filter: India and its key cities/states must be present,
# and remote or foreign locations are rejected
IN_KEYS=['india','hyderabad','secunderabad','telangana','andhra','ap','chennai','bangalore','bengaluru','mumbai','delhi','kolkata','pune','kochi','coimbatore','vizag','vizianagaram','warangal','karimnagar','nizamabad','mahbubnagar','medak','nalgonda','khammam','kurnool','kadapa','tirupati','guntur','vijayawada','ongole','nellore','andhra pradesh','south india']
EX_KEYS=['remote','usa','us-','united states','uk-','united kingdom','europe','dubai','uae','canada','australia','germany','wfh']
def is_hyd(j):
 h=' '+j.get('haystack','')+' '
 if any(k in h for k in EX_KEYS):return False
 return any(k in h for k in IN_KEYS)
def norm(j):
 j['title']=j.get('title','').strip();j['company']=j.get('company','Unknown').strip();j['location']=j.get('location','Not specified').strip();j['url']=j.get('url','').strip();j['haystack']=j.get('haystack',f"{j['title']} {j['company']} {j['location']}").lower();return j
def unique(js):
 d={}
 for j in js:
  k=j.get('url') or j.get('id')
  if k:d.setdefault(k,j)
 return list(d.values())
def fetch_linkedin():
 out=[]
 for q in ['accounts executive tally','junior accountant fresher','gst finance fresher']:
  u='https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords='+quote_plus(q)+'&location=Hyderabad%2C%20Telangana&f_TPR=r86400&start=0'
  try:
   r=requests.get(u,headers=HEAD,timeout=TIMEOUT)
   if r.status_code!=200:print('LinkedIn HTTP',r.status_code);continue
   s=BeautifulSoup(r.text,'html.parser')
   for c in s.select('li'):
    t=c.select_one('h3.base-search-card__title');a=c.select_one('a.base-card__full-link')
    if not t or not a:continue
    co=c.select_one('h4.base-search-card__subtitle');lo=c.select_one('span.job-search-card__location');dt=c.select_one('time');url=a.get('href','').split('?')[0]
    out.append(norm({'id':c.get('data-entity-urn') or url,'title':t.get_text(' ',strip=True),'company':co.get_text(' ',strip=True) if co else 'Unknown','location':lo.get_text(' ',strip=True) if lo else 'Hyderabad','url':url,'posted':dt.get('datetime','')[:10] if dt else '','haystack':c.get_text(' ',strip=True),'source':'LinkedIn'}))
  except requests.RequestException as e:print('LinkedIn failed:',e)
 return unique(out)
def fetch_indeed():
 out=[]
 for q in ['accounts executive tally','junior accountant fresher','gst finance fresher']:
  u='https://in.indeed.com/jobs?q='+quote_plus(q)+'&l=Hyderabad%2C+Telangana&fromage=1'
  try:
   r=requests.get(u,headers=HEAD,timeout=TIMEOUT)
   if r.status_code!=200:print('Indeed HTTP',r.status_code);continue
   s=BeautifulSoup(r.text,'html.parser')
   for c in s.select('div.job_seen_beacon') or s.select('div[data-jk]'):
    t=c.select_one('h2.jobTitle a,h2 a')
    if not t:continue
    jk=c.get('data-jk') or t.get('data-jk','');href=f'https://in.indeed.com/viewjob?jk={jk}' if jk else t.get('href','');
    if href.startswith('/'):href='https://in.indeed.com'+href
    co=c.select_one("[data-testid='company-name'],span.companyName");lo=c.select_one("[data-testid='text-location'],div.companyLocation");sa=c.select_one("[data-testid='attribute_snippet'],.salary-snippet-container");dt=c.select_one('.date,span.date')
    out.append(norm({'id':jk or href,'title':t.get_text(' ',strip=True),'company':co.get_text(' ',strip=True) if co else 'Unknown','location':lo.get_text(' ',strip=True) if lo else 'Hyderabad','url':href,'posted':dt.get_text(' ',strip=True) if dt else '','haystack':c.get_text(' ',strip=True),'source':'Indeed','salary':sa.get_text(' ',strip=True) if sa else ''}))
  except requests.RequestException as e:print('Indeed failed:',e)
 return unique(out)
def send(m):
 r=requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',json={'chat_id':CHAT,'text':m,'parse_mode':'HTML'},timeout=15);print('Telegram HTTP',r.status_code)
def main():
 allj=[]
 for f in [fetch_linkedin,fetch_indeed]:
  try:
   j=f();print(f.__name__,len(j));allj+=j
  except Exception as e:print(f.__name__,'failed safely:',e)
 allj=unique(allj);seen={}
 try:
  with open(SEEN,encoding='utf-8') as f:seen=json.load(f).get('seen',{})
 except (OSError,ValueError):pass
 now=datetime.now(timezone.utc);cut=now-timedelta(days=DAYS);alerts=[]
 for j in allj:
  if not j.get('url') or not any(k in j.get('haystack','') for k in KEYWORDS) or not is_hyd(j) or j['url'] in seen:continue
  try:posted=datetime.strptime(j.get('posted','')[:10],'%Y-%m-%d').replace(tzinfo=timezone.utc)
  except ValueError:posted=None
  if posted and posted<cut:continue
  alerts.append(j);seen[j['url']]=now.isoformat()
 with open(SEEN,'w',encoding='utf-8') as f:json.dump({'last_run_utc':now.isoformat(),'seen':{u:t for u,t in seen.items() if t>(now-timedelta(days=60)).isoformat()}},f,indent=2)
 if not alerts:print('No new matching jobs.');return
 chunks=[];cur='📋 <b>NEW JOB ALERTS (Hyderabad/India Only)</b>\n📥 '+str(len(alerts))+' new match(es)\n\n'
 for j in alerts[:12]:
  p=(' | Posted: '+html.escape(j['posted'])) if j.get('posted') else '';sal=('\n💰 '+html.escape(j['salary'])) if j.get('salary') else ''
  b=f"💼 <b>{html.escape(j['title'].title())}</b>\n🏢 {html.escape(j['company'])}\n📍 {html.escape(j['location'])}{p}{sal}\n🌐 {j.get('source','')}\n🔗 <a href='{html.escape(j['url'],quote=True)}'>Apply Here</a>\n\n"
  if len(cur)+len(b)>3800:chunks.append(cur);cur='📋 <b>NEW JOB ALERTS (Hyderabad/India Only)</b>\n\n'
  cur+=b
 chunks.append(cur)
 for c in chunks:send(c)
 print('Sent',min(12,len(alerts)),'alerts')
if __name__=='__main__':main()

# quote is used only for Telegram URL escaping
from urllib.parse import quote
