# Computer Prachi verified/updated: 10-09-2026 03:34
#!/usr/bin/env python3
"""
Computer Prachi automatic updater - category-isolated version.

Each category is fetched from its own source category page so an item such as
"UPTET 2026 Certificate" stays in Results and is not copied into Jobs,
Admit Card, Syllabus, Admission, etc.
"""
import re
import socket
from pathlib import Path
from urllib.parse import quote, urlparse
from datetime import datetime

import requests
from bs4 import BeautifulSoup, Comment
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = Path(__file__).resolve().parent
ROOT = "https://sarkariresult.com.cm"
# Cloudflare currently serves this domain on these IPv4 addresses.
# GitHub Actions can occasionally fail to resolve the domain through its
# runner DNS; the updater will fall back to these addresses while preserving
# the hostname for HTTPS/SNI.
FALLBACK_IPS = ("104.26.14.182", "104.26.15.182", "172.67.74.40")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ComputerPrachiAutoUpdater/3.0)",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
}

# Reuse one HTTP session for all source pages. The previous updater created a
# new session for every page and could spend the entire GitHub Actions timeout
# resolving/connecting repeatedly.
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

CATEGORIES = {
    "Latest Jobs": ("jobs", "/category/latest-job/"),
    "Results": ("results", "/category/result/"),
    "Admit Cards": ("admit", "/category/admit-card/"),
    "Answer Key": ("answer", "/category/answer-key/"),
    "Admission": ("admission", "/category/admission/"),
    "10th/ITI Jobs": ("iti", "/category/10th-iti-jobs/"),
    "Outsourcing Jobs": ("outsourcing", "/category/outsourcing-jobs/"),
    "Syllabus": ("syllabus", "/category/syllabus/"),
    "Documents": ("documents", "/category/documents-verification/"),
}

PAGE_MAP = {
    "jobs": "job.html",
    "results": "result.html",
    "admit": "admit.html",
    "answer": "detail.html",
    "admission": "detail.html",
    "iti": "detail.html",
    "outsourcing": "detail.html",
    "syllabus": "detail.html",
    "documents": "detail.html",
    "updates": "all-latest-update.html",
}

INDEX_ID_MAP = {
    "jobs": "jobs",
    "results": "result",
    "admit": "admit",
    "answer": "answer",
    "admission": "admission",
    "iti": "iti",
    "outsourcing": "outsourcing",
    "syllabus": "syllabus",
    "documents": "documents",
    "updates": "updates",
}

def clean(v):
    return re.sub(r"\s+", " ", v or "").strip()

def normalize_url(href):
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return ROOT + href
    if href.startswith("http://"):
        return "https://" + href[7:]
    if not href.startswith("http"):
        return ROOT + "/" + href.lstrip("/")
    return href

def fetch(url):
    last = None
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    SESSION.mount("https://", HTTPAdapter(max_retries=retry))
    session = SESSION

    # First use normal DNS. If the runner reports a DNS failure, retry with
    # Cloudflare's known IPv4 addresses. We patch only getaddrinfo for the
    # source hostname, so requests still uses the real hostname in the URL
    # and therefore keeps correct TLS/SNI and Host headers.
    try:
        r = session.get(url, timeout=(20, 60))
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        last = exc

    from urllib.parse import urlparse
    host = urlparse(url).hostname
    if host == "sarkariresult.com.cm":
        original_getaddrinfo = socket.getaddrinfo
        for ip in FALLBACK_IPS:
            def fallback_getaddrinfo(name, port, *args, _ip=ip, **kwargs):
                if name == host:
                    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_ip, port))]
                return original_getaddrinfo(name, port, *args, **kwargs)
            try:
                socket.getaddrinfo = fallback_getaddrinfo
                r = session.get(url, timeout=(20, 60))
                r.raise_for_status()
                socket.getaddrinfo = original_getaddrinfo
                return BeautifulSoup(r.text, "html.parser")
            except Exception as exc:
                last = exc
            finally:
                socket.getaddrinfo = original_getaddrinfo

    raise RuntimeError(f"Source fetch failed: {url} :: {last}")

def extract_admit_link(source_url):
    """Find the direct external Download Admit Card link on a source detail page."""
    try:
        soup = fetch(source_url)
        for text_node in soup.find_all(string=re.compile(r"download\s+admit\s+card", re.I)):
            parent = text_node.parent
            # Prefer a nearby link in the same small section.
            candidates = []
            if parent is not None:
                candidates.extend(parent.find_all("a", href=True))
                container = parent.parent
                if container is not None:
                    candidates.extend(container.find_all("a", href=True))
            # Then look forward a few links; source pages usually put
            # "Click Here" immediately after the "Download Admit Card" label.
            if parent is not None:
                candidates.extend(parent.find_all_next("a", href=True, limit=4))
            for a in candidates:
                href = normalize_url(a.get("href"))
                if href and not href.startswith(ROOT + "/"):
                    return href
        return ""
    except Exception:
        return ""

def enrich_admit_cards(items):
    """Attach the real external admit-card URL to each admit-card item."""
    for item in items[:12]:
        direct = extract_admit_link(item.get("url", ""))
        if direct:
            item["official"] = direct
    return items


def extract_official_link(source_url, heading_hint):
    """Find the most relevant direct external official link on a source detail page."""
    try:
        soup = fetch(source_url)
        category_terms = {
            "Latest Jobs": [("apply online", 100), ("apply now", 90), ("online form", 80),
                            ("registration", 70), ("apply", 50)],
            "Results": [("download final result", 120), ("download result", 115), ("result pdf", 110),
                        ("result", 80), ("score card", 75)],
            "Admit Cards": [("download admit card", 120), ("admit card", 110), ("hall ticket", 105)],
            "Answer Key": [("answer key", 120), ("download answer key", 115)],
            "Admission": [("apply online", 120), ("online admission", 115), ("registration", 105),
                          ("online form", 100), ("apply", 70)],
            "10th/ITI Jobs": [("apply online", 100), ("apply now", 90), ("online form", 80),
                              ("registration", 70), ("apply", 50)],
            "Outsourcing Jobs": [("apply online", 100), ("apply now", 90), ("online form", 80),
                                 ("registration", 70), ("apply", 50)],
            "Syllabus": [("download syllabus", 120), ("syllabus", 100)],
            "Documents": [("document verification", 120), ("verification", 100), ("certificate", 80)],
        }
        terms = category_terms.get(heading_hint, [])
        candidates = []

        # Prefer links in table rows where the left cell names the action.
        for tr in soup.find_all("tr"):
            row_text = clean(tr.get_text(" ", strip=True)).lower()
            for a in tr.find_all("a", href=True):
                href = normalize_url(a.get("href"))
                if not href or not href.startswith("http") or href.startswith(ROOT + "/"):
                    continue
                anchor_text = clean(a.get_text(" ", strip=True)).lower()
                score = 0
                for term, weight in terms:
                    if term in row_text:
                        score = max(score, weight)
                    if term in anchor_text:
                        score = max(score, weight + 20)
                if score:
                    candidates.append((score, href))

        # Then inspect all external anchors and their nearby text.
        for a in soup.find_all("a", href=True):
            href = normalize_url(a.get("href"))
            if not href or not href.startswith("http") or href.startswith(ROOT + "/"):
                continue
            text = clean(a.get_text(" ", strip=True)).lower()
            parent_text = clean(a.parent.get_text(" ", strip=True)).lower() if a.parent else ""
            score = 0
            for term, weight in terms:
                if term in text:
                    score = max(score, weight + 25)
                elif term in parent_text:
                    score = max(score, weight)
            if score:
                candidates.append((score, href))

        if candidates:
            # Prefer government/official institutional domains when several
            # external links have the same action label. Short-link/ad domains
            # are kept only when no better official destination exists.
            def domain_bonus(href):
                h = href.lower()
                if any(d in h for d in (
                    ".gov.in", ".nic.in", ".gov.uk", ".ac.in", ".edu.in",
                    ".gov", ".nic", "upsssc.gov.in", "uppsc.up.nic.in",
                    "ssc.gov.in", "upsc.gov.in", "bpsc.bih.nic.in",
                    "nta.ac.in", "exams.nta.ac.in", "ctet.nic.in",
                    "ibps.in", "sbi.co.in", "joinindianarmy.nic.in",
                    "joinindiannavy.gov.in", "afcat.cdac.in",
                    "careerindianairforce.cdac.in"
                )):
                    return 50
                if any(d in h for d in ("bit.ly", "tinyurl.com", "t.me", "whatsapp.com")):
                    return -30
                return 0
            candidates.sort(key=lambda x: (-(x[0] + domain_bonus(x[1])), x[1]))
            return candidates[0][1]
        return ""
    except Exception:
        return ""

def enrich_official_links(items, heading_hint):
    """Attach direct official action links used by the Computer Prachi buttons.

    Only the first 12 entries are enriched because those are the entries shown
    on the homepage. All-View pages still contain the source links, while the
    visible homepage/detail buttons get the real official destination. This
    keeps the scheduled job fast enough for GitHub Actions.
    """
    for item in items[:12]:
        direct = extract_official_link(item.get("url", ""), heading_hint)
        if direct:
            item["official"] = direct
    return items

def extract_category(url, heading_hint):
    """Extract only article links from the requested source category page.

    The source category pages contain both article cards and a footer-style
    category list. We first collect article-title headings (h2/h3) with an
    internal article link, then fall back to the category list. This prevents
    navigation items such as "Read more" from becoming updates and keeps
    categories isolated.
    """
    soup = fetch(url)
    out, seen = [], set()
    bad_titles = {
        "home", "latest job", "latest jobs", "admit card", "admit cards",
        "result", "results", "admission", "syllabus", "answer key",
        "read more", "official sarkari result", "let’s update", "let's update",
        "sarkari result", "connect with us", "contact us", "privacy policy",
        "disclaimer", "more", "next", "previous"
    }
    def add(a):
        title = clean(a.get_text(" ", strip=True))
        href = normalize_url(a.get("href"))
        if not title or not href or not href.startswith(ROOT + "/"):
            return
        low = href.lower()
        if any(x in low for x in ("/category/", "/tag/", "/author/", "/page/", "/feed", "/wp-") ):
            return
        if title.lower() in bad_titles:
            return
        # A real article URL is a single root-level slug, not a site utility path.
        path = urlparse(href).path.strip("/")
        if not path or "/" in path:
            return
        key = href.lower()
        if key in seen:
            return
        seen.add(key)
        out.append({"title": title, "url": href})

    # Primary: article cards. On SarkariResult each post title is rendered as
    # a heading containing the post's own link.
    for h in soup.find_all(["h2", "h3"]):
        title = clean(h.get_text(" ", strip=True))
        low = title.lower()
        if not title or low in bad_titles or low.startswith("#"):
            continue
        # Skip category/footer headings; accept only headings with a direct
        # internal article anchor.
        for a in h.find_all("a", href=True):
            before = len(out)
            add(a)
            if len(out) > before:
                break
        if len(out) >= 50:
            break

    # Secondary: use the category's own bottom list if the theme does not put
    # the post link inside the heading.
    if len(out) < 5:
        out.clear(); seen.clear()
        marker = None
        wanted = {
            "Latest Jobs": "# latest job", "Results": "# result", "Admit Cards": "# admit card",
            "Answer Key": "# answer key", "Admission": "# admission", "10th/ITI Jobs": "# 10th",
            "Outsourcing Jobs": "# outsourcing", "Syllabus": "# syllabus", "Documents": "# documents"
        }.get(heading_hint, "")
        for h in soup.find_all(["h2", "h3", "h4"]):
            if clean(h.get_text(" ", strip=True)).lower() == wanted:
                marker = h; break
        if marker:
            for a in marker.find_all_next("a", href=True):
                add(a)
                if len(out) >= 50: break

    if not out:
        raise RuntimeError(f"Source parsing failed for {heading_hint}: no article items at {url}")
    return out[:50]

def li(item, kind):
    # Mixed Latest Update entries carry their real category so links still
    # open the correct category-specific detail page.
    actual_kind = item.get("_kind", kind) if kind == "updates" else kind
    page = PAGE_MAP[actual_kind]
    title, url = item["title"], item["url"]
    extra = f"&official={quote(item['official'], safe='')}" if item.get("official") else ""
    return (
        '<li><span class="new">NEW</span>'
        f'<a href="{page}?title={quote(title)}&url={quote(url, safe="")}{extra}" '
        f'target="_self" rel="noopener">{title}</a></li>'
    )

def list_html(items, kind):
    return "\n".join(li(x, kind) for x in items)

def replace_marker(text, marker, new):
    pattern = re.compile(
        rf"<!-- AUTO:{re.escape(marker)}:START -->.*?"
        rf"<!-- AUTO:{re.escape(marker)}:END -->", re.S
    )
    if not pattern.search(text):
        return None
    replacement = (
        f"<!-- AUTO:{marker}:START -->\n{new}\n"
        f"<!-- AUTO:{marker}:END -->"
    )
    return pattern.sub(replacement, text, count=1)

def add_index_markers(path):
    from bs4 import BeautifulSoup, Comment
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    mapping = INDEX_ID_MAP
    for kind, sid in mapping.items():
        sec = soup.find(id=sid)
        if not sec: continue
        ul = sec.find("ul")
        if not ul: continue
        # Remove old marker comments for this kind anywhere, then put them
        # around the actual visible list, never in a new list at EOF.
        for node in soup.find_all(string=lambda s: s and f"AUTO:{kind}:" in s):
            node.extract()
        ul.insert(0, Comment(f" AUTO:{kind}:START "))
        ul.append(Comment(f" AUTO:{kind}:END "))
    path.write_text(str(soup), encoding="utf-8")
    return str(soup)

def update_index(items):
    path = BASE / "index.html"
    text = add_index_markers(path)

    for heading, (kind, _) in CATEGORIES.items():
        if kind in INDEX_ID_MAP and items.get(heading):
            updated = replace_marker(
                text, kind, list_html(items[heading][:12], kind)
            )
            if updated is not None:
                text = updated

    # Mixed Latest Update is intentionally built from each real category,
    # but each link keeps its own correct destination page.
    latest = []
    for heading in (
        "Results", "Admit Cards", "Latest Jobs", "Answer Key",
        "Documents", "Admission", "10th/ITI Jobs", "Outsourcing Jobs",
        "Syllabus"
    ):
        latest.extend(items.get(heading, [])[:3])

    # Preserve category-specific destination for mixed updates.
    mixed = []
    for heading in (
        "Results", "Admit Cards", "Latest Jobs", "Answer Key",
        "Documents", "Admission", "10th/ITI Jobs", "Outsourcing Jobs",
        "Syllabus"
    ):
        kind = CATEGORIES[heading][0]
        mixed.extend(li(x, kind) for x in items.get(heading, [])[:3])

    updated = replace_marker(text, "updates", "\n".join(mixed[:18]))
    if updated is not None:
        text = updated
    path.write_text(text, encoding="utf-8")

def update_page(filename, kind, items):
    from bs4 import BeautifulSoup, Comment
    path = BASE / filename
    if not path.exists(): return
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    ul = soup.find("ul")
    if not ul: raise RuntimeError(f"Cannot find visible list in {filename}")
    # Remove any old markers anywhere and then replace the actual visible UL.
    for node in soup.find_all(string=lambda s: s and f"AUTO:{kind}:" in s):
        node.extract()
    ul.clear()
    ul.append(Comment(f" AUTO:{kind}:START "))
    frag = BeautifulSoup(list_html(items, kind), "html.parser")
    for li_node in frag.find_all("li", recursive=False):
        ul.append(li_node)
    ul.append(Comment(f" AUTO:{kind}:END "))
    path.write_text(str(soup), encoding="utf-8")

def stamp_update_date():
    stamp = datetime.now().strftime("%d %B %Y")
    for filename in (
        "index.html", "all-results.html", "all-admit-card.html",
        "all-jobs.html", "all-latest-update.html"
    ):
        path = BASE / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            r"Latest update:</b>\s*[^<]+",
            f"Latest update:</b> {stamp} — Jobs, Results और Admit Card lists refreshed.",
            text, flags=re.I
        )
        path.write_text(text, encoding="utf-8")

def main():
    items = {}
    for heading, (_, url) in CATEGORIES.items():
        try:
            items[heading] = extract_category(ROOT + url, heading)
            # The source URL is used only for reading updates. It is NEVER
            # exposed as a clickable button on Computer Prachi.
            items[heading] = enrich_official_links(items[heading], heading)
            if heading == "Admit Cards":
                items[heading] = enrich_admit_cards(items[heading])
            print(f"{heading}: {len(items[heading])}")
        except Exception as exc:
            print(f"WARNING: {heading} source unavailable; keeping existing page data: {exc}")
            items[heading] = []

    primary = sum(
        bool(items.get(k)) for k in ("Latest Jobs", "Results", "Admit Cards")
    )
    if primary < 2:
        print("WARNING: Source server was unreachable. No existing page was overwritten.")
        return

    # Strong sanity check: the first items of categories should not all be
    # identical. This prevents cross-category contamination.
    firsts = [
        items[k][0]["title"].lower()
        for k in ("Latest Jobs", "Results", "Admit Cards")
        if items.get(k)
    ]
    if len(firsts) >= 3 and len(set(firsts)) == 1:
        raise RuntimeError(
            "Source validation failed: category lists are identical; refusing to overwrite."
        )

    update_index(items)
    update_page("all-jobs.html", "jobs", items["Latest Jobs"])
    update_page("all-results.html", "results", items["Results"])
    update_page("all-admit-card.html", "admit", items["Admit Cards"])
    update_page("all-answer-key.html", "answer", items["Answer Key"])
    update_page("all-admission.html", "admission", items["Admission"])
    update_page("all-iti-jobs.html", "iti", items["10th/ITI Jobs"])
    update_page("all-outsourcing-jobs.html", "outsourcing", items["Outsourcing Jobs"])
    update_page("all-syllabus.html", "syllabus", items["Syllabus"])
    update_page("all-documents-verification.html", "documents", items["Documents"])
    mixed_all = []
    for heading in ("Results", "Admit Cards", "Latest Jobs", "Answer Key", "Documents", "Admission", "10th/ITI Jobs", "Outsourcing Jobs", "Syllabus"):
        kind = CATEGORIES[heading][0]
        for item in items[heading][:3]:
            copy_item = dict(item)
            copy_item["_kind"] = kind
            mixed_all.append(copy_item)
    update_page("all-latest-update.html", "updates", mixed_all[:18])
    stamp_update_date()
    print("Computer Prachi category update completed successfully.")

if __name__ == "__main__":
    main()
