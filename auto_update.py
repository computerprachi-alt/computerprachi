#!/usr/bin/env python3
import re
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
BASE=Path(__file__).resolve().parent
SOURCE='https://sarkariresult.com.cm/'
CATEGORIES={'Latest Jobs':('jobs','job.html'),'Results':('results','result.html'),'Admit Cards':('admit','detail.html'),'Answer Key':('answer','detail.html'),'Admission':('admission','detail.html'),'10th/ITI Jobs':('iti','detail.html'),'Outsourcing Jobs':('outsourcing','detail.html'),'Syllabus':('syllabus','detail.html')}
def clean(s): return re.sub(r'\s+',' ',s or '').strip()
def fetch():
 r=requests.get(SOURCE,timeout=30,headers={'User-Agent':'Mozilla/5.0 (compatible; ComputerPrachiAutoUpdater/1.0)'}); r.raise_for_status(); return BeautifulSoup(r.text,'html.parser')
def section_items(soup,heading):
 h=None
 for tag in soup.find_all(['h1','h2','h3','h4','strong','div']):
  if clean(tag.get_text(' ',strip=True)).lower()==heading.lower(): h=tag; break
 if not h:return []
 ul=h.find_next('ul')
 if not ul:return []
 out=[]
 for a in ul.find_all('a',href=True):
  title=clean(a.get_text(' ',strip=True)); href=a.get('href','').strip()
  if not title or not href or href.startswith('#'): continue
  if href.startswith('/'): href='https://sarkariresult.com.cm'+href
  elif href.startswith('http://'): href='https://'+href[7:]
  elif not href.startswith('http'): href='https://sarkariresult.com.cm/'+href.lstrip('/')
  if 'sarkariresult.com.cm' not in href: continue
  if not any(x['url']==href for x in out): out.append({'title':title,'url':href})
 return out
def li(x,kind):
 page='job.html' if kind=='jobs' else ('result.html' if kind=='results' else 'detail.html')
 return f'<li><span class="new">NEW</span><a href="{page}?title={quote(x["title"])}&url={quote(x["url"],safe="")}" target="_self" rel="noopener">{x["title"]}</a></li>'
def list_html(items,kind): return '\n'.join(li(x,kind) for x in items)
def replace_marker(text,marker,new):
 pat=re.compile(rf'<!-- AUTO:{re.escape(marker)}:START -->.*?<!-- AUTO:{re.escape(marker)}:END -->',re.S)
 return pat.sub(f'<!-- AUTO:{marker}:START -->\n{new}\n<!-- AUTO:{marker}:END -->',text,count=1)
def add_index_markers(p):
 text=p.read_text(encoding='utf-8')
 for sid in ['jobs','result','admit','answer','admission','syllabus']:
  pat=re.compile(rf'(<section[^>]*id="{sid}"[^>]*>.*?<h2>.*?</h2>)<ul>(.*?)</ul>',re.S|re.I)
  m=pat.search(text)
  if m and f'<!-- AUTO:{sid}:START -->' not in text:
   text=text[:m.start()]+m.group(1)+f'<ul><!-- AUTO:{sid}:START -->{m.group(2)}<!-- AUTO:{sid}:END --></ul>'+text[m.end():]
 p.write_text(text,encoding='utf-8'); return text
def update_index(items):
 p=BASE/'index.html'; text=add_index_markers(p)
 for heading,(kind,_) in CATEGORIES.items():
  if kind not in ['jobs','results','admit','answer','admission','syllabus']: continue
  text=replace_marker(text,kind,list_html(items[heading][:25],kind))
 p.write_text(text,encoding='utf-8')
def update_page(filename,kind,items):
 p=BASE/filename
 if not p.exists(): return
 text=p.read_text(encoding='utf-8')
 if f'<!-- AUTO:{kind}:START -->' not in text:
  m=re.search(r'(<section[^>]*>.*?<h2>.*?</h2>)<ul>(.*?)</ul>',text,re.S|re.I)
  if m: text=text[:m.start()]+m.group(1)+f'<ul><!-- AUTO:{kind}:START -->{m.group(2)}<!-- AUTO:{kind}:END --></ul>'+text[m.end():]
 p.write_text(replace_marker(text,kind,list_html(items,kind)),encoding='utf-8')
def create_page(filename,title,kind,items):
 p=BASE/filename
 if p.exists(): return
 rows=list_html(items,kind)
 p.write_text(f'''<!doctype html><html lang="hi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | Computer Prachi</title><style>body{{margin:0;background:#f5f5f5;font-family:Arial;color:#222}}.wrap{{max-width:1100px;margin:auto;background:#fff;min-height:100vh}}header{{background:#07145c;color:#fff;padding:20px}}header h1{{margin:0}}main{{padding:15px}}section{{border:1px solid #ddd}}h2{{margin:0;background:#c40000;color:#fff;padding:10px}}ul{{margin:0;padding:12px 28px}}li{{padding:6px 0;line-height:1.4}}a{{color:#0019a8}}.new{{color:#c40000;font-weight:700;font-size:10px;margin-right:5px}}.back{{display:inline-block;margin-top:15px;text-decoration:none}}</style></head><body><div class="wrap"><header><h1>Computer Prachi</h1><div>Sarkari Naukri, Results, Admit Card, Answer Key, Admission, Syllabus</div></header><main><section><h2>{title}</h2><ul><!-- AUTO:{kind}:START -->{rows}<!-- AUTO:{kind}:END --></ul></section><a class="back" href="index.html">« Back to Home</a></main></div></body></html>''',encoding='utf-8')
def main():
 soup=fetch(); items={h:section_items(soup,h) for h in CATEGORIES}
 if not items['Latest Jobs'] and not items['Results'] and not items['Admit Cards']: raise RuntimeError('No recognizable source data; refusing to overwrite site.')
 update_index(items); update_page('all-jobs.html','jobs',items['Latest Jobs']); update_page('all-results.html','results',items['Results'])
 create_page('all-admit-card.html','All Admit Cards','admit',items['Admit Cards']); create_page('all-answer-key.html','All Answer Keys','answer',items['Answer Key']); create_page('all-admission.html','All Admission / Online Forms','admission',items['Admission']); create_page('all-iti-jobs.html','All 10th / ITI Jobs','iti',items['10th/ITI Jobs']); create_page('all-outsourcing-jobs.html','All Outsourcing Jobs','outsourcing',items['Outsourcing Jobs']); create_page('all-syllabus.html','All Syllabus','syllabus',items['Syllabus'])
 print({k:len(v) for k,v in items.items()})
if __name__=='__main__': main()
