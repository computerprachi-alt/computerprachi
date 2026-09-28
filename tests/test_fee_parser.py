import sys
from pathlib import Path
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import auto_update

CASES = [
    ("General / OBC / EWS : ₹850/- SC / ST / PH : ₹175/- Payment Mode (Online): Debit Card, Credit Card, Internet Banking", {'feeGen':'₹ 850/-','feeOBC':'₹ 850/-','feeSC':'₹ 175/-','feeST':'₹ 175/-'}),
    ("Application Fee : ₹100/- For SC/ST/PH : ₹0/- For All Category Female : ₹0/-", {'feeGen':'₹ 100/-','feeSC':'₹ 0/-','feeST':'₹ 0/-','feeFemale':'₹ 0/-'}),
    ("General / OBC / EWS : ₹500/- For SC / ST / EBC : ₹250/- For All Category female : ₹250/- Fee Refund : General / OBC : Rs. 400/- will be refunded", {'feeGen':'₹ 500/-','feeOBC':'₹ 500/-','feeSC':'₹ 250/-','feeST':'₹ 250/-','feeFemale':'₹ 250/-'}),
    ("Application Fee : ₹100/- For SC/ST/PH : ₹0/- For All Category Female : ₹0/-", {'feeGen':'₹ 100/-','feeSC':'₹ 0/-','feeST':'₹ 0/-','feeFemale':'₹ 0/-'}),
    ("For General, OBC, EWS: ₹850/- For SC, ST, PH: ₹175/- Payment Mode (Online): Debit Card, Credit Card", {'feeGen':'₹ 850/-','feeOBC':'₹ 850/-','feeSC':'₹ 175/-','feeST':'₹ 175/-'}),
]

for text, expected in CASES:
    original = auto_update.fetch
    auto_update.fetch = lambda _url, t=text: BeautifulSoup('<html><body><tr><td>'+t+'</td></tr></body></html>', 'html.parser')
    try:
        got = auto_update.extract_job_details('https://example.invalid/test')
    finally:
        auto_update.fetch = original
    for k,v in expected.items():
        if got[k] != v:
            raise AssertionError(f'{text}\n{k}: expected {v!r}, got {got[k]!r}')
    if 'Payment Mode' in got.get('feeGen','') or 'Refund' in got.get('feeGen',''):
        raise AssertionError(f'fee contamination: {got}')

print(f'FEE PARSER FIXTURES PASSED: {len(CASES)}/{len(CASES)}')
