import json, re
from pathlib import Path
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
JOB = BASE / 'job.html'
LIST = BASE / 'all-jobs.html'
DATA = BASE / 'cp-auto-job-data.js'

FEE_FIELDS = ('feeGen','feeOBC','feeSC','feeST','feeReserved','feeFemale')
BAD_FEE = re.compile(r'payment\s+mode|fee\s*refund|fess\s*refund|will\s+be\s+refunded|refunded\s+to', re.I)
FALLBACK = re.compile(r'^See(?: \d{4})? Official Notification$', re.I)

soup = BeautifulSoup(LIST.read_text(encoding='utf-8'), 'html.parser')
links = soup.select('a[href^="job.html?"]')
if len(links) < 60:
    raise SystemExit(f'FAIL: Latest Jobs links found only {len(links)}; expected at least 60')

data_text = DATA.read_text(encoding='utf-8')
m = re.search(r'window\.CP_AUTO_JOB_DATA\s*=\s*(\{.*\});?\s*$', data_text, re.S)
if not m:
    raise SystemExit('FAIL: cp-auto-job-data.js JSON object not found')
data = json.loads(m.group(1))

errors = []
seen_titles = set()
seen_keys = set()
for a in links:
    title = a.get_text(' ', strip=True)
    href = a.get('href','')
    qm = re.search(r'[?&]key=([^&]+)', href)
    key = None
    if qm:
        from urllib.parse import unquote
        key = unquote(qm.group(1))
    if title in seen_titles:
        errors.append(f'duplicate title: {title}')
    seen_titles.add(title)
    if key:
        if key not in data:
            errors.append(f'missing generated key: {key} ({title})')
        else:
            seen_keys.add(key)
    if title not in data:
        errors.append(f'missing generated title: {title}')

for key, item in data.items():
    if not isinstance(item, dict):
        errors.append(f'{key}: metadata is not an object')
        continue
    for field in FEE_FIELDS:
        v = item.get(field, '')
        if not isinstance(v, str):
            errors.append(f'{key} {field}: non-string value')
            continue
        if BAD_FEE.search(v):
            errors.append(f'{key} {field}: fee contains refund/payment-mode prose: {v}')
        if len(v) > 120:
            errors.append(f'{key} {field}: fee too long ({len(v)} chars)')
        if re.search(r'\bFor\s+(?:SC|ST|EBC|PH|PWD|All\s+Category|Group\s+C)\b', v, re.I):
            errors.append(f'{key} {field}: category boundary leaked into value: {v}')

    for field in ('begin','last','feeLast'):
        v = item.get(field, '')
        if isinstance(v, str) and re.search(r'\b(?:Exam Date|Admit Card|Result(?: Declared Date)?|Payment Mode|Candidates are advised)\b', v, re.I):
            errors.append(f'{key} {field}: date field contains another labelled field: {v}')

# The page itself has a defensive display filter so malformed auto data cannot
# overwrite a good hard-coded fallback.
job_text = JOB.read_text(encoding='utf-8')
if 'CP_BAD_FEE' not in job_text or 'cpUsable' not in job_text:
    errors.append('job.html missing fee safety filter')
if 'cp-original-job-guide' not in job_text:
    errors.append('job.html missing original information guide')

if errors:
    print(f'VALIDATION FAILED: {len(errors)} error(s)')
    for e in errors[:100]: print(' -', e)
    raise SystemExit(1)

print(f'VALIDATION PASSED: {len(links)} Latest Jobs checked; {len(data)} generated records checked; 0 errors')
