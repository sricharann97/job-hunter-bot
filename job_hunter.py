import html,json,os,time

from datetime import datetime,timezone,timedelta

from urllib.parse import quote_plus

import requests

from bs4 import BeautifulSoup

TOKEN=os.environ['TELEGRAM_TOKEN']; CHAT=os.environ['TELEGRAM_CHAT_ID']

KEYWORDS=['accounts executive','accounts assistant','junior accountant','accountant trainee','tally operator','gst assistant','gst executive','tds assistant','billing executive','finance assistant','bookkeeper','back office finance','mis executive','accountant','finance','accounting','tally','audit','clerk','data entry','admin']

SEEN='seen_jobs.json'; TIMEOUT=20; DAYS=30

HEAD={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36','Accept-Language':'en-IN,en;q=0.9'}

def norm(j):
    
 j['title']=j.get('title','').strip();j['company']=j.get('company','Unknown').strip();j['location']=j.get('location','Not specified').strip();j['url']=j.get('url','').strip();j['haystack']=j.get('haystack',f"{j['title']} {j['company']} {j['location']}").lower();return j
    
def unique(js):
    
 d={}
    
 for j in js:
     
  k=j.get('url') or j.get('id')
     
  if k:d.setdefault(k,j)
      
 return list(d.values())
    
def fetch_arbeitnow():
    
 r=requests.get('https://www.arbeitnow.com/api/job-board-api',timeout=TIMEOUT);r.raise_for_status();out=[]
    
 for x in r.json().get('data',[])[:200]:out.append(norm({'id':x.get('slug',x.get('url','')),'title':x.get('title',''),'company':x.get('company_name','Unknown'),'location':x.get('location','Not specified'),'url':x.get('url',''),'posted':(x.get('date') or '')[:10],'haystack':f"{x.get('title','')} {x.get('description','')} {x.get('company_name','')}",'source':'Arbeitnow'}))
     
 return out
    
def fetch_remoteok():
    
 r=requests.get('https://remoteok.com/api',headers=HEAD,timeout=TIMEOUT)
    
 if r.status_code!=200:return []
     
 data=r.json();data=data[1:] if isinstance(data,list) else data;out=[]
    
 for x in data[:100]:
     
  posted=datetime.fromtimestamp(x['epoch'],timezone.utc).date().isoformat() if x.get('epoch') else ''
     
  out.append(norm({'id':x.get('slug',x.get('url','')),'title':x.get('position',x.get('title','')),'company':x.get('company','Unknown'),'location':x.get('location','Remote'),'url':x.get('apply_url') or x.get('url',''),'posted':posted,'haystack':f"{x.get('position','')} {' '.join(x.get('tags',[]) or [])} {x.get('description','')}",'source':'RemoteOK'}))
     
 return out
    
def fetch_muse():
    
 out=[]
    
 for p in range(1,4):
     
  try:
      
   r=requests.get(f'https://www.themuse.com/api/public/jobs?page={p}',timeout=TIMEOUT)
      
   if r.status_code!=200:break
       
   rows=r.json().get('results',[])
      
   if not rows:break
       
   for x in rows:
       
    cats=[z.get('name','') for z in x.get('categories',[])];tags=[z.get('name','') for z in x.get('tags',[])];locs=[z.get('name','') for z in x.get('locations',[])];co=(x.get('company') or {}).get('name','Unknown');slug=co.lower().replace(' ','-').replace('.','')
       
    out.append(norm({'id':str(x.get('id','')),'title':x.get('name',''),'company':co,'location':', '.join(locs) or 'US','url':f"https://www.themuse.com/jobs/{slug}/{x.get('id')}",'posted':(x.get('publication_date') or '')[:10],'haystack':f"{x.get('name','')} {' '.join(cats)} {' '.join(tags)} {' '.join(locs)}",'source':'The Muse'}))
       
   time.sleep(.3)
      
  except requests.RequestException as e:print('Muse failed:',e);break
      
 return out
    
def fetch_linkedin():
    
 out=[]
    
 for q in ['accounts executive tally','junior accountant fresher','gst finance fresher']:
     
  u='https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords='+quote_plus(q)+'&location=Hyderabad%2C%20Telangana&f_TPR=r86400&start=0'
     
  try:
      
   r=requests.get(u,headers=HEAD,timeout=TIMEOUT)
      
   if r.status_code!=200:print('LinkedIn HTTP',r.status_code);continue
       
   s=BeautifulSoup(r.text,'html.parser')
      
   for c in s.select('li'):
       
    t=c.select_one('h3.base-search-card










































