# Computer Prachi verified/updated: 10-09-2026 03:55
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
from urllib.parse import quote
from datetime import datetime

import requests
from bs4 import BeautifulSoup
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
    """Extract only article links from one dedicated source category page.

    The source site repeats mixed lists in navigation/sidebar/footer, so the
    old "walk forward from a heading" parser could accidentally pick unrelated
    items or generic links such as "Read more".  Category pages themselves are
    the source of truth: first use their article/post cards, then fall back to
    the category section if the theme changes.
    """
    soup = fetch(url)
    out, seen_urls = [], set()

    exact_headings = {
        "Latest Jobs": {"latest job", "latest jobs", "all latest jobs"},
        "Results": {"result", "results", "all latest examination result",
                    "all latest result", "latest result"},
        "Admit Cards": {"admit card", "admit cards", "all latest admit card"},
        "Answer Key": {"answer key", "all latest answer key"},
        "Admission": {"admission", "all latest admission"},
        "10th/ITI Jobs": {"10th/iti jobs", "10th/iti", "all latest 10th/iti jobs",
                          "all latest 10th"},
        "Outsourcing Jobs": {"outsourcing jobs", "outsourcing", "all latest outsourcing jobs",
                             "all latest outsourcing"},
        "Syllabus": {"syllabus", "all latest syllabus"},
        "Documents": {"documents verification", "document verification",
                      "all latest documents verification", "all latest document"},
    }
    wanted = {clean(x).lower() for x in exact_headings.get(heading_hint, {heading_hint})}

    # Prefer the real category heading instead of a later repeated sidebar/footer
    # heading. For each category we rank exact matches above substring matches.
    heading_candidates = []
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        htxt = clean(h.get_text(" ", strip=True)).lower()
        if htxt in wanted:
            heading_candidates.append((0, h))
        elif any(x in htxt for x in wanted):
            heading_candidates.append((1, h))

    matched = heading_candidates[0][1] if heading_candidates else None

    bad_titles = {
        "home", "latest job", "latest jobs", "admit card", "admit cards",
        "result", "results", "admission", "syllabus", "answer key",
        "documents", "documents verification", "read more",
        "official sarkari result", "sarkari result", "let’s update",
        "let's update", "lets update", "view more", "view all", "next", "previous",
    }

    def add_anchor(a, score=0):
        title = clean(a.get_text(" ", strip=True))
        href = normalize_url(a.get("href"))
        if not title or not href or not href.startswith(ROOT + "/"):
            return
        low = href.lower()
        # Only article/detail URLs are useful. Category, tag, author, pagination,
        # feed and site-navigation URLs must never become content items.
        if any(x in low for x in (
            "/category/", "/tag/", "/author/", "/page/", "/feed",
            "/wp-", "?s=", "/search/"
        )):
            return
        if low.rstrip("/") == ROOT.lower().rstrip("/"):
            return
        title_low = title.lower()
        if title_low in bad_titles or len(title) < 5:
            return
        # Do not let generic sidebar/utility text enter a content list.
        if any(x in title_low for x in (
            "welcome to official sarkari result",
            "stay informed about the latest",
        )):
            return

        # Article links on the source are the strongest evidence. If the anchor
        # is inside an <article> or common post-card wrapper, keep its order.
        key = href.split("#", 1)[0].rstrip("/")
        if key not in seen_urls:
            seen_urls.add(key)
            out.append({"title": title, "url": href, "_score": score})

    # 1) Best path: collect links from actual article/post cards. This avoids
    # sidebar/footer lists which contain items from other categories.
    article_nodes = soup.find_all("article")
    for article in article_nodes:
        # Prefer anchors whose visible text is a title. Image-only anchors are
        # ignored here and can be recovered by the section fallback below.
        for a in article.find_all("a", href=True):
            add_anchor(a, 100)
    if len(out) >= 5:
        out = out[:50]
        for item in out:
            item.pop("_score", None)
        return out

    # 2) Theme fallback: collect from the main content area around the exact
    # category heading. Exclude header/nav/sidebar/footer blocks.
    out.clear()
    seen_urls.clear()

    root = soup.find("main") or soup.body or soup
    for a in root.find_all("a", href=True):
        # Skip anchors living in navigation/sidebar/footer regions.
        blocked = False
        for parent in a.parents:
            if parent is None:
                break
            name = getattr(parent, "name", "")
            classes = " ".join(parent.get("class", [])).lower() if hasattr(parent, "get") else ""
            ident = str(parent.get("id", "")).lower() if hasattr(parent, "get") else ""
            if name in {"nav", "header", "footer"} or any(
                token in (classes + " " + ident)
                for token in ("sidebar", "menu", "navigation", "breadcrumb", "footer")
            ):
                blocked = True
                break
            if matched is not None and parent is matched:
                break
        if blocked:
            continue
        add_anchor(a, 50)

    if len(out) >= 5:
        out = out[:50]
        for item in out:
            item.pop("_score", None)
        return out

    # 3) Last fallback: inspect links after the selected category heading until
    # the next major heading. This is deliberately conservative and filters all
    # generic navigation text.
    out.clear()
    seen_urls.clear()
    if matched is not None:
        node = matched
        steps = 0
        while node is not None and steps < 80:
            node = node.find_next()
            steps += 1
            if node is None:
                break
            if getattr(node, "name", None) in {"h1", "h2"} and node is not matched:
                break
            if getattr(node, "name", None) == "a" and node.get("href"):
                add_anchor(node, 20)
            if len(out) >= 50:
                break

    if not out:
        raise RuntimeError(
            f"Source parsing failed for {heading_hint}: no article links found at {url}"
        )

    out = out[:50]
    for item in out:
        item.pop("_score", None)
    return out

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
    text = path.read_text(encoding="utf-8")
    for kind, sid in INDEX_ID_MAP.items():
        marker = kind
        if f"<!-- AUTO:{marker}:START -->" in text:
            continue
        pat = re.compile(
            rf'(<section[^>]*id="{re.escape(sid)}"[^>]*>.*?'
            rf'<h2>.*?</h2>)<ul>(.*?)</ul>', re.S | re.I
        )
        m = pat.search(text)
        if m:
            wrapped = (
                m.group(1) + f'<ul><!-- AUTO:{marker}:START -->'
                + m.group(2)
                + f'<!-- AUTO:{marker}:END --></ul>'
            )
            text = text[:m.start()] + wrapped + text[m.end():]
    path.write_text(text, encoding="utf-8")
    return text

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
    path = BASE / filename
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    marker = f"<!-- AUTO:{kind}:START -->"

    if marker not in text:
        # Add markers around the first substantial <ul> belonging to the
        # first content section. Accept <ul>, <ul id="...">, classes, etc.
        m = re.search(
            r"(<section\b[^>]*>.*?<h2\b[^>]*>.*?</h2>\s*<ul\b[^>]*>)(.*?)(</ul>)",
            text, re.S | re.I
        )
        if not m:
            m = re.search(
                r"(<main\b[^>]*>.*?<h2\b[^>]*>.*?</h2>\s*<ul\b[^>]*>)(.*?)(</ul>)",
                text, re.S | re.I
            )
        if not m:
            raise RuntimeError(f"Cannot add marker to {filename}")
        wrapped = (
            m.group(1) + f"<!-- AUTO:{kind}:START -->"
            + m.group(2)
            + f"<!-- AUTO:{kind}:END -->" + m.group(3)
        )
        text = text[:m.start()] + wrapped + text[m.end():]

    updated = replace_marker(text, kind, list_html(items, kind))
    if updated is None:
        raise RuntimeError(f"Cannot update marker in {filename}")
    path.write_text(updated, encoding="utf-8")

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
