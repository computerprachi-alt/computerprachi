# Computer Prachi verified/updated: 28-09-2026
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

FALLBACK_IPS = ("104.26.14.182", "104.26.15.182", "172.67.74.40")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ComputerPrachiAutoUpdater/3.0)",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
}

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

    try:
        r = session.get(url, timeout=(20, 60))
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        last = exc

    host = urlparse(url).hostname

    if host == "sarkariresult.com.cm":
        original_getaddrinfo = socket.getaddrinfo

        for ip in FALLBACK_IPS:

            def fallback_getaddrinfo(
                name,
                port,
                *args,
                _ip=ip,
                **kwargs
            ):
                if name == host:
                    return [
                        (
                            socket.AF_INET,
                            socket.SOCK_STREAM,
                            6,
                            "",
                            (_ip, port),
                        )
                    ]
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

        for text_node in soup.find_all(
            string=re.compile(r"download\s+admit\s+card", re.I)
        ):
            parent = text_node.parent
            candidates = []

            if parent is not None:
                candidates.extend(parent.find_all("a", href=True))

                container = parent.parent
                if container is not None:
                    candidates.extend(container.find_all("a", href=True))

            if parent is not None:
                candidates.extend(
                    parent.find_all_next("a", href=True, limit=4)
                )

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
            "Latest Jobs": [
                ("apply online", 100),
                ("apply now", 90),
                ("online form", 80),
                ("registration", 70),
                ("apply", 50),
            ],
            "Results": [
                ("download final result", 120),
                ("download result", 115),
                ("result pdf", 110),
                ("result", 80),
                ("score card", 75),
            ],
            "Admit Cards": [
                ("download admit card", 120),
                ("admit card", 110),
                ("hall ticket", 105),
            ],
            "Answer Key": [
                ("answer key", 120),
                ("download answer key", 115),
            ],
            "Admission": [
                ("apply online", 120),
                ("online admission", 115),
                ("registration", 105),
                ("online form", 100),
                ("apply", 70),
            ],
            "10th/ITI Jobs": [
                ("apply online", 100),
                ("apply now", 90),
                ("online form", 80),
                ("registration", 70),
                ("apply", 50),
            ],
            "Outsourcing Jobs": [
                ("apply online", 100),
                ("apply now", 90),
                ("online form", 80),
                ("registration", 70),
                ("apply", 50),
            ],
            "Syllabus": [
                ("download syllabus", 120),
                ("syllabus", 100),
            ],
            "Documents": [
                ("document verification", 120),
                ("verification", 100),
                ("certificate", 80),
            ],
        }

        terms = category_terms.get(heading_hint, [])
        candidates = []

        for tr in soup.find_all("tr"):
            row_text = clean(
                tr.get_text(" ", strip=True)
            ).lower()

            for a in tr.find_all("a", href=True):
                href = normalize_url(a.get("href"))

                if (
                    not href
                    or not href.startswith("http")
                    or href.startswith(ROOT + "/")
                ):
                    continue

                anchor_text = clean(
                    a.get_text(" ", strip=True)
                ).lower()

                score = 0

                for term, weight in terms:
                    if term in row_text:
                        score = max(score, weight)

                    if term in anchor_text:
                        score = max(score, weight + 20)

                if score:
                    candidates.append((score, href))

        for a in soup.find_all("a", href=True):
            href = normalize_url(a.get("href"))

            if (
                not href
                or not href.startswith("http")
                or href.startswith(ROOT + "/")
            ):
                continue

            text = clean(
                a.get_text(" ", strip=True)
            ).lower()

            parent_text = (
                clean(
                    a.parent.get_text(" ", strip=True)
                ).lower()
                if a.parent
                else ""
            )

            score = 0

            for term, weight in terms:
                if term in text:
                    score = max(score, weight + 25)
                elif term in parent_text:
                    score = max(score, weight)

            if score:
                candidates.append((score, href))

        if candidates:

            def domain_bonus(href):
                h = href.lower()

                if any(
                    d in h
                    for d in (
                        ".gov.in",
                        ".nic.in",
                        ".gov.uk",
                        ".ac.in",
                        ".edu.in",
                        ".gov",
                        ".nic",
                        "upsssc.gov.in",
                        "uppsc.up.nic.in",
                        "ssc.gov.in",
                        "upsc.gov.in",
                        "bpsc.bih.nic.in",
                        "nta.ac.in",
                        "exams.nta.ac.in",
                        "ctet.nic.in",
                        "ibps.in",
                        "sbi.co.in",
                        "joinindianarmy.nic.in",
                        "joinindiannavy.gov.in",
                        "afcat.cdac.in",
                        "careerindianairforce.cdac.in",
                    )
                ):
                    return 50

                if any(
                    d in h
                    for d in (
                        "bit.ly",
                        "tinyurl.com",
                        "t.me",
                        "whatsapp.com",
                    )
                ):
                    return -30

                return 0

            candidates.sort(
                key=lambda x: (
                    -(x[0] + domain_bonus(x[1])),
                    x[1],
                )
            )

            return candidates[0][1]

        return ""

    except Exception:
        return ""


def enrich_official_links(items, heading_hint):
    """Attach direct official action links used by the Computer Prachi buttons."""
    for item in items[:12]:
        direct = extract_official_link(
            item.get("url", ""),
            heading_hint
        )

        if direct:
            item["official"] = direct

    return items


def extract_category(url, heading_hint):
    """Extract up to 70 article links from the source category and its pages."""
    out = []
    seen = set()

    bad_titles = {
        "home",
        "latest job",
        "latest jobs",
        "admit card",
        "admit cards",
        "result",
        "results",
        "admission",
        "syllabus",
        "answer key",
        "read more",
        "official sarkari result",
        "let’s update",
        "let's update",
        "sarkari result",
        "connect with us",
        "contact us",
        "privacy policy",
        "disclaimer",
        "more",
        "next",
        "previous",
    }

    def add(a):
        title = clean(a.get_text(" ", strip=True))
        href = normalize_url(a.get("href"))

        if not title or not href or not href.startswith(ROOT + "/"):
            return

        low = href.lower()

        if any(
            x in low
            for x in (
                "/category/",
                "/tag/",
                "/author/",
                "/page/",
                "/feed",
                "/wp-",
            )
        ):
            return

        if title.lower() in bad_titles:
            return

        path = urlparse(href).path.strip("/")

        if not path or "/" in path:
            return

        key = href.lower()

        if key in seen:
            return

        seen.add(key)

        out.append(
            {
                "title": title,
                "url": href,
            }
        )

    base = url.rstrip("/")

    max_pages = (
        7
        if heading_hint in (
            "Latest Jobs",
            "Results",
            "Admit Cards",
        )
        else 1
    )

    page_urls = [
        base
    ] + [
        f"{base}/page/{n}/"
        for n in range(2, max_pages + 1)
    ]

    for page_url in page_urls:

        try:
            soup = fetch(page_url)

        except Exception:

            if page_url != base:
                break

            raise

        before_page = len(out)

        for h in soup.find_all(["h2", "h3"]):
            title = clean(
                h.get_text(" ", strip=True)
            )

            low = title.lower()

            if not title or low in bad_titles or low.startswith("#"):
                continue

            for a in h.find_all("a", href=True):
                before = len(out)

                add(a)

                if len(out) > before:
                    break

            if len(out) >= 70:
                break

        if len(out) - before_page < 5:

            wanted = {
                "Latest Jobs": "# latest job",
                "Results": "# result",
                "Admit Cards": "# admit card",
                "Answer Key": "# answer key",
                "Admission": "# admission",
                "10th/ITI Jobs": "# 10th",
                "Outsourcing Jobs": "# outsourcing",
                "Syllabus": "# syllabus",
                "Documents": "# documents",
            }.get(heading_hint, "")

            marker = None

            for h in soup.find_all(["h2", "h3", "h4"]):

                if (
                    clean(
                        h.get_text(" ", strip=True)
                    ).lower()
                    == wanted
                ):
                    marker = h
                    break

            if marker:

                for a in marker.find_all_next(
                    "a",
                    href=True,
                ):
                    add(a)

                    if len(out) >= 70:
                        break

        if len(out) >= 70:
            break

        if (
            len(out) == before_page
            and page_url != base
        ):
            break

    if not out:
        raise RuntimeError(
            f"Source parsing failed for {heading_hint}: "
            f"no article items at {url}"
        )

    return out[:70]


def title_category(title):
    """Return the most specific content category implied by a title."""
    t = clean(title).lower()

    if any(
        x in t
        for x in (
            "answer key",
            "answer-key",
            "response sheet",
            "response-sheet",
        )
    ):
        return "answer"

    if any(
        x in t
        for x in (
            "admit card",
            "hall ticket",
            "exam city",
            "exam date",
            "exam schedule",
            "interview letter",
            "interview schedule",
            "typing test date",
            "physical admit",
            "physical test",
            "pet admit",
        )
    ):
        return "admit"

    if any(
        x in t
        for x in (
            "result",
            "score card",
            "scorecard",
            "certificate",
            "allotment result",
            "merit list",
            "selection list",
            "final result",
        )
    ):
        return "results"

    if any(
        x in t
        for x in (
            "recruitment",
            "vacancy",
            "vacancies",
            "online form",
            "apply online",
            "application form",
            "notification",
        )
    ):
        return "jobs"

    return ""


def enforce_category_separation(items):
    """Remove cross-category items and move obvious typed updates to their home."""
    buckets = {
        k: list(v or [])
        for k, v in items.items()
    }

    moved = {
        "answer": [],
        "admit": [],
        "results": [],
        "jobs": [],
    }

    for heading, kind in (
        ("Latest Jobs", "jobs"),
        ("Results", "results"),
        ("Admit Cards", "admit"),
        ("Answer Key", "answer"),
    ):

        kept = []

        for item in buckets.get(heading, []):

            detected = title_category(
                item.get("title", "")
            )

            if detected and detected != kind:
                moved[detected].append(item)
            else:
                kept.append(item)

        buckets[heading] = kept

    heading_for = {
        "answer": "Answer Key",
        "admit": "Admit Cards",
        "results": "Results",
        "jobs": "Latest Jobs",
    }

    for kind, arr in moved.items():

        target = heading_for[kind]

        existing = {
            clean(
                x.get("title", "")
            ).lower()
            for x in buckets[target]
        }

        for item in arr:

            key = clean(
                item.get("title", "")
            ).lower()

            if key and key not in existing:
                buckets[target].append(item)
                existing.add(key)

    return buckets


def li(item, kind):
    actual_kind = (
        item.get("_kind", kind)
        if kind == "updates"
        else kind
    )

    page = PAGE_MAP[actual_kind]

    title = item["title"]
    source_url = item["url"]

    source_key = (
        urlparse(source_url).path.strip("/")
        + "/"
    )

    extra = (
        f"&official={quote(item['official'], safe='')}"
        if item.get("official")
        else ""
    )

    key_extra = (
        f"&key={quote(source_key, safe='')}"
        if source_key.strip("/")
        else ""
    )

    return (
        '<li><span class="new">NEW</span>'
        f'<a href="{page}?title={quote(title)}'
        f'{key_extra}{extra}" '
        f'target="_self" rel="noopener">'
        f'{title}</a></li>'
    )


def list_html(items, kind):
    return "\n".join(
        li(x, kind)
        for x in items
    )


def replace_marker(text, marker, new):
    pattern = re.compile(
        rf"<!-- AUTO:{re.escape(marker)}:START -->.*?"
        rf"<!-- AUTO:{re.escape(marker)}:END -->",
        re.S,
    )

    if not pattern.search(text):
        return None

    replacement = (
        f"<!-- AUTO:{marker}:START -->\n"
        f"{new}\n"
        f"<!-- AUTO:{marker}:END -->"
    )

    return pattern.sub(
        replacement,
        text,
        count=1,
    )


def add_index_markers(path):
    soup = BeautifulSoup(
        path.read_text(encoding="utf-8"),
        "html.parser",
    )

    mapping = INDEX_ID_MAP

    for kind, sid in mapping.items():

        sec = soup.find(id=sid)

        if not sec:
            continue

        ul = sec.find("ul")

        if not ul:
            continue

        for node in soup.find_all(
            string=lambda s: s and f"AUTO:{kind}:" in s
        ):
            node.extract()

        ul.insert(
            0,
            Comment(
                f" AUTO:{kind}:START "
            ),
        )

        ul.append(
            Comment(
                f" AUTO:{kind}:END "
            )
        )

    path.write_text(
        str(soup),
        encoding="utf-8",
    )

    return str(soup)


def update_index(items):
    path = BASE / "index.html"

    text = add_index_markers(path)

    for heading, (kind, _) in CATEGORIES.items():

        if kind in INDEX_ID_MAP and items.get(heading):

            updated = replace_marker(
                text,
                kind,
                list_html(
                    items[heading][:30],
                    kind,
                ),
            )

            if updated is not None:
                text = updated

    mixed = []

    for heading in (
        "Results",
        "Admit Cards",
        "Latest Jobs",
        "Answer Key",
        "Documents",
        "Admission",
        "10th/ITI Jobs",
        "Outsourcing Jobs",
        "Syllabus",
    ):

        kind = CATEGORIES[heading][0]

        mixed.extend(
            li(x, kind)
            for x in items.get(
                heading,
                [],
            )[:10]
        )

    updated = replace_marker(
        text,
        "updates",
        "\n".join(mixed[:70]),
    )

    if updated is not None:
        text = updated

    path.write_text(
        text,
        encoding="utf-8",
    )


def update_page(filename, kind, items):
    path = BASE / filename

    if not path.exists():
        return

    soup = BeautifulSoup(
        path.read_text(encoding="utf-8"),
        "html.parser",
    )

    ul = soup.find("ul")

    if not ul:
        raise RuntimeError(
            f"Cannot find visible list in {filename}"
        )

    for node in soup.find_all(
        string=lambda s: s and f"AUTO:{kind}:" in s
    ):
        node.extract()

    ul.clear()

    ul.append(
        Comment(
            f" AUTO:{kind}:START "
        )
    )

    frag = BeautifulSoup(
        list_html(items, kind),
        "html.parser",
    )

    for li_node in frag.find_all(
        "li",
        recursive=False,
    ):
        ul.append(li_node)

    ul.append(
        Comment(
            f" AUTO:{kind}:END "
        )
    )

    path.write_text(
        str(soup),
        encoding="utf-8",
    )


def stamp_update_date():
    stamp = datetime.now().strftime(
        "%d %B %Y"
    )

    for filename in (
        "index.html",
        "all-results.html",
        "all-admit-card.html",
        "all-jobs.html",
        "all-latest-update.html",
    ):

        path = BASE / filename

        if not path.exists():
            continue

        text = path.read_text(
            encoding="utf-8"
        )

        text = re.sub(
            r"Latest update:</b>\s*[^<]+",
            f"Latest update:</b> {stamp} — "
            f"Jobs, Results और Admit Card lists refreshed.",
            text,
            flags=re.I,
        )

        path.write_text(
            text,
            encoding="utf-8",
        )


def extract_job_details(source_url):
    """Extract recruitment dates and application fees without cross-field bleed."""

    fallback = "See Official Notification"

    result = {
        "begin": fallback,
        "last": fallback,
        "feeLast": fallback,
        "feeGen": fallback,
        "feeOBC": fallback,
        "feeSC": fallback,
        "feeST": fallback,
        "feeReserved": fallback,
        "feeFemale": fallback,
        "feeMode": fallback,
    }

    try:
        soup = fetch(source_url)

        lines = []

        for node in soup.find_all(
            [
                "tr",
                "li",
                "p",
                "h1",
                "h2",
                "h3",
                "h4",
            ]
        ):

            txt = clean(
                node.get_text(
                    " ",
                    strip=True,
                )
            )

            if txt and len(txt) <= 600:
                lines.append(txt)

        if not lines:

            for node in soup.find_all("div"):

                txt = clean(
                    node.get_text(
                        " ",
                        strip=True,
                    )
                )

                if txt and len(txt) <= 600:
                    lines.append(txt)

        seen = set()

        lines = [
            x
            for x in lines
            if not (
                x in seen
                or seen.add(x)
            )
        ]

        def value_after(
            patterns,
            boundary,
            max_len=160,
        ):

            for line in lines:

                for pat in patterns:

                    m = re.search(
                        pat
                        + r"\s*(?:[:\-]|)\s*(.*?)"
                        + boundary,
                        line,
                        re.I,
                    )

                    if m:

                        v = clean(
                            m.group(1)
                        ).strip(
                            " -:|,;"
                        )

                        if v and len(v) <= max_len:
                            return v

            return ""

        date_boundary = (
            r"(?=\s+(?:application\s+begin|"
            r"start(?:ing)?\s+date|opening\s+date|"
            r"last\s+date|closing\s+date|"
            r"fee\s+payment|pay\s+exam\s+fee|"
            r"exam\s+date|admit\s+card|"
            r"result\s+available)\b|$)"
        )

        result["begin"] = value_after(
            [
                r"(?:online\s+apply\s+)?application\s+begin(?:\s+date)?",
                r"(?:online\s+apply\s+)?start(?:ing)?\s+date",
                r"application\s+start\s+date",
                r"online\s+application\s+start\s+date",
                r"form\s+begin(?:\s+date)?",
            ],
            date_boundary,
        ) or fallback

        result["last"] = value_after(
            [
                r"last\s+date\s+(?:for\s+)?(?:apply\s+online|online\s+apply)",
                r"(?:online\s+apply\s+)?last\s+date",
                r"closing\s+date",
                r"application\s+last\s+date",
            ],
            date_boundary,
        ) or fallback

        result["feeLast"] = value_after(
            [
                r"last\s+date\s+for\s+fee\s+payment",
                r"last\s+date\s+for\s+pay(?:ing)?\s+(?:the\s+)?(?:application\s+)?fee",
                r"pay\s+exam\s+fee\s+last\s+date",
                r"fee\s+(?:payment\s+)?last\s+date",
            ],
            date_boundary,
        ) or result["last"]

        label = (
            r"(?:for\s+)?(?:"
            r"general\s*/\s*obc\s*/\s*ews|"
            r"general\s*/\s*obc|"
            r"sc\s*/\s*st\s*/\s*(?:ebc|pwd|ph)|"
            r"sc\s*/\s*st|"
            r"obc\s*/\s*ews|"
            r"all\s+category\s+(?:candidate\s+)?(?:female|women)|"
            r"application\s+fee|exam\s+fee|"
            r"general|gen|obc|ews|sc|st|ebc|pwd|ph|female|women|"
            r"payment\s+mode(?:\s*\(\s*online\s*\))?"
            r")"
        )

        fee_segment_re = re.compile(
            r"(?P<label>"
            + label
            + r")\s*(?:[:\-]\s*)?"
            r"(?P<value>.*?)"
            r"(?=\s+(?:for\s+)?(?:"
            r"general\s*/\s*obc\s*/\s*ews|"
            r"general\s*/\s*obc|"
            r"sc\s*/\s*st\s*/\s*(?:ebc|pwd|ph)|"
            r"sc\s*/\s*st|"
            r"obc\s*/\s*ews|"
            r"all\s+category\s+(?:candidate\s+)?(?:female|women)|"
            r"application\s+fee|exam\s+fee|"
            r"general|gen|obc|ews|sc|st|ebc|pwd|ph|female|women|"
            r"payment\s+mode)"
            r"|$)",
            re.I,
        )

        def amount_or_text(value):

            v = clean(value)

            if re.search(
                r"\b(?:fee\s*refund|fess\s*refund|"
                r"will\s+be\s+refunded|refunded\s+to)\b",
                v,
                re.I,
            ):

                v = re.split(
                    r"\b(?:fee\s*refund|fess\s*refund|"
                    r"will\s+be\s+refunded|refunded\s+to)\b",
                    v,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip()

            m = re.search(
                r"(?:₹\s*|Rs\.?\s*|INR\s*)"
                r"([0-9][0-9,]*(?:\.\d{1,2})?)"
                r"\s*(?:/-?|/)?",
                v,
                re.I,
            )

            if m:
                return "₹ " + m.group(1) + "/-"

            if re.search(
                r"\b(?:no\s+fee|nil|free|not\s+applicable)\b",
                v,
                re.I,
            ):
                return v[:80]

            return ""

        def set_fee(label_text, value_text):

            lab = re.sub(
                r"\s+",
                " ",
                label_text.lower(),
            ).strip()

            lab = re.sub(
                r"^for\s+",
                "",
                lab,
            )

            val = amount_or_text(value_text)

            if not val:
                return

            if "payment mode" in lab:
                return

            if (
                lab.startswith(
                    "general / obc / ews"
                )
                or lab.startswith(
                    "general/obc/ews"
                )
            ):
                result["feeGen"] = val
                result["feeOBC"] = val

            elif (
                lab.startswith(
                    "general / obc"
                )
                or lab.startswith(
                    "general/obc"
                )
            ):
                result["feeGen"] = val
                result["feeOBC"] = val

            elif (
                lab.startswith("sc / st")
                or lab.startswith("sc/st")
            ):
                result["feeSC"] = val
                result["feeST"] = val
                result["feeReserved"] = val

            elif (
                "obc / ews" in lab
                or lab in ("obc", "ews")
            ):
                result["feeOBC"] = val

            elif lab in ("general", "gen"):
                result["feeGen"] = val

            elif lab == "sc":
                result["feeSC"] = val

            elif lab == "st":
                result["feeST"] = val

            elif lab in ("ebc", "pwd", "ph"):
                result["feeReserved"] = val

            elif (
                "all category" in lab
                or lab in ("female", "women")
            ):
                result["feeFemale"] = val

            elif (
                lab in (
                    "application fee",
                    "exam fee",
                )
                and result["feeGen"] == fallback
            ):
                result["feeGen"] = val

        for line in lines:

            low = line.lower()

            if not any(
                x in low
                for x in (
                    "fee",
                    "general",
                    "obc",
                    "ews",
                    "sc",
                    "st",
                    "female",
                    "women",
                )
            ):
                continue

            fee_part = re.split(
                r"\b(?:fee\s*refund|fess\s*refund)\b",
                line,
                maxsplit=1,
                flags=re.I,
            )[0]

            fee_part = re.sub(
                r"\bGeneral\s*,\s*OBC\s*,\s*EWS\b",
                "General/OBC/EWS",
                fee_part,
                flags=re.I,
            )

            fee_part = re.sub(
                r"\bSC\s*,\s*ST\s*,\s*(?:PH|PWD)\b",
                "SC/ST/PH",
                fee_part,
                flags=re.I,
            )

            for m in fee_segment_re.finditer(fee_part):
                set_fee(
                    m.group("label"),
                    m.group("value"),
                )

            pm = re.search(
                r"payment\s+mode(?:\s*\(\s*online\s*\))?"
                r"\s*[:\-]?\s*(.+)$",
                line,
                re.I,
            )

            if pm:
                result["feeMode"] = clean(
                    pm.group(1)
                )[:300]

        if result["feeGen"] == fallback:

            for line in lines:

                if re.search(
                    r"\b(?:fee\s*refund|fess\s*refund)\b",
                    line,
                    re.I,
                ):
                    line = re.split(
                        r"\b(?:fee\s*refund|fess\s*refund)\b",
                        line,
                        maxsplit=1,
                        flags=re.I,
                    )[0]

                m = re.search(
                    r"\b(?:application|exam)\s+fee\b"
                    r"\s*[:\-]?\s*(.*)$",
                    line,
                    re.I,
                )

                if m:

                    val = amount_or_text(
                        m.group(1)
                    )

                    if val:
                        result["feeGen"] = val
                        break

        if result["feeReserved"] != fallback:

            if result["feeSC"] == fallback:
                result["feeSC"] = result["feeReserved"]

            if result["feeST"] == fallback:
                result["feeST"] = result["feeReserved"]

        return result

    except Exception as exc:

        print(
            f"WARNING: Could not extract job metadata "
            f"from {source_url}: {exc}"
        )

        return result


# ============================================================
# PERMANENT VERIFIED FEE OVERRIDES
# ============================================================
#
# These values are applied on every automatic update.
# cp-auto-job-data.js is generated output only.
# The permanent source of truth is this FEE_OVERRIDES dictionary.
#
FEE_OVERRIDES = {

    "Bank of India BOI SO Online Form 2026 – Date Extend": {
        "feeGen": "₹ 1180/-", "feeOBC": "₹ 1180/-", "feeSC": "₹ 175/-",
        "feeST": "₹ 175/-", "feeReserved": "₹ 175/-",
        "feeFemale": "₹ 1180/-", "feeMode": "Online"
    },

    "JSSC 10+2 Inter Level JILCCE Online form 2026": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 50/-",
        "feeST": "₹ 50/-",
        "feeReserved": "₹ 50/-",
        "feeFemale": "As per category",
        "feeMode": "Online",
    },

    "HPSC Food Safety Officer (FSO) Online Form 2026": {
        "feeGen": "₹ 1000/-",
        "feeOBC": "₹ 250/-",
        "feeSC": "₹ 250/-",
        "feeST": "₹ 250/-",
        "feeReserved": "₹ 0/- (PwBD Haryana)",
        "feeFemale": "₹ 250/-",
        "feeMode": "Online",
    },

    "ITBP HC (Motor Mechanic) Online Form 2026": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 0/-",
        "feeST": "₹ 0/-",
        "feeReserved": "₹ 0/- (ESM)",
        "feeFemale": "₹ 0/-",
        "feeMode": "Online",
    },

    "Indian Army TGC 145 Online Form 2026": {
        "feeGen": "₹ 0/-",
        "feeOBC": "₹ 0/-",
        "feeSC": "₹ 0/-",
        "feeST": "₹ 0/-",
        "feeReserved": "₹ 0/-",
        "feeFemale": "₹ 0/-",
        "feeMode": "No Application Fee",
    },

    "UP PGT Teacher Online Form 2026 (2607 Posts)": {
        "feeGen": "₹ 1500/-",
        "feeOBC": "₹ 1500/-",
        "feeSC": "₹ 750/-",
        "feeST": "₹ 750/-",
        "feeReserved": "₹ 500/- (PwD)",
        "feeFemale": "As per category",
        "feeMode": "Online",
    },

    "NTPC Assistant Officer Online Form 2026": {
        "feeGen": "₹ 500/-",
        "feeOBC": "₹ 500/-",
        "feeSC": "₹ 0/-",
        "feeST": "₹ 0/-",
        "feeReserved": "₹ 0/- (PwBD/Ex-Servicemen)",
        "feeFemale": "₹ 0/-",
        "feeMode": "Online / SBI Pay-in-Slip",
    },

    "IBPS Hindi Officer Online Form 2026": {
        "feeGen": "₹ 1000/-",
        "feeOBC": "₹ 1000/-",
        "feeSC": "₹ 1000/-",
        "feeST": "₹ 1000/-",
        "feeReserved": "₹ 1000/-",
        "feeFemale": "₹ 1000/-",
        "feeMode": "Online",
    },

    "MPESB MP Police SI, Subedar Correction Form 2026": {
        "feeGen": "₹ 500/-",
        "feeOBC": "₹ 250/-",
        "feeSC": "₹ 250/-",
        "feeST": "₹ 250/-",
        "feeReserved": "₹ 250/- (MP Domicile)",
        "feeFemale": "₹ 250/-",
        "feeMode": "Online + Portal Charge Extra",
    },

    "SSC CPO SI CAPF Online Form 2026": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 0/-",
        "feeST": "₹ 0/-",
        "feeReserved": "₹ 0/- (Ex-Servicemen eligible for reservation)",
        "feeFemale": "₹ 0/-",
        "feeMode": "Online — BHIM UPI / Net Banking / Card",
    },

    "IIT BHU Non Teaching Online Form 2026 – Date Extend": {
        "feeGen": "₹ 500/- (Group B) / ₹ 250/- (Group C)",
        "feeOBC": "₹ 500/- (Group B) / ₹ 250/- (Group C)",
        "feeSC": "₹ 0/-",
        "feeST": "₹ 0/-",
        "feeReserved": "₹ 0/- (PwBD)",
        "feeFemale": "₹ 0/-",
        "feeMode": "Online",
    },

    "SSC CHSL 10+2 Online Form 2026": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 0/-",
        "feeST": "₹ 0/-",
        "feeReserved": "₹ 0/- (SC / ST / PwBD / eligible Ex-Servicemen)",
        "feeFemale": "₹ 0/-",
        "feeMode": "Online — BHIM UPI / Net Banking / Card",
    },

    "Indian Army Dental Corps Online Form 2026": {
        "feeGen": "₹ 200/-",
        "feeOBC": "₹ 200/-",
        "feeSC": "₹ 200/-",
        "feeST": "₹ 200/-",
        "feeReserved": "₹ 200/-",
        "feeFemale": "₹ 200/-",
        "feeMode": "Online",
    },

    "Rajasthan Safai Karmchari Online Form 2026 (24,752 posts)": {
        "feeGen": "₹ 600/-",
        "feeOBC": "₹ 400/-",
        "feeSC": "₹ 400/-",
        "feeST": "₹ 400/-",
        "feeReserved": "₹ 400/- (EWS/MBC/PwD etc.)",
        "feeFemale": "As per category",
        "feeMode": "Online / Rajasthan SSO / E-Mitra",
    },

    # --------------------------------------------------------
    # NEW VERIFIED PERMANENT CORRECTIONS
    # --------------------------------------------------------

    "BPSC School Teacher TRE 4.0 Online Form 2026 (33,320 Posts)": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 100/-",
        "feeST": "₹ 100/-",
        "feeReserved": "₹ 100/-",
        "feeFemale": "₹ 100/-",
        "feeMode": "Online",
    },

    "JSSC Para Teacher JTAACCE Online form 2026 (7299 Posts) – Start": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 50/-",
        "feeST": "₹ 50/-",
        "feeReserved": "₹ 50/- (Jharkhand SC/ST)",
        "feeFemale": "As per category",
        "feeMode": "Online",
    },

    "Assam Rifles Technical / Tradesman Online Form 2026": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 0/-",
        "feeST": "₹ 0/-",
        "feeReserved": "₹ 0/- (Ex-Servicemen)",
        "feeFemale": "Not Eligible",
        "feeMode": "Online / SBI Challan",
    },

    "BPSC School Teacher TRE 4.0 Online Form 2026 (32,388 Posts)": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 100/-",
        "feeST": "₹ 100/-",
        "feeReserved": "₹ 100/-",
        "feeFemale": "₹ 100/-",
        "feeMode": "Online",
    },

    "RRC SR Apprentice Online Form 2026 (4471 Posts) – Last Date Today": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 0/-",
        "feeST": "₹ 0/-",
        "feeReserved": "₹ 0/- (PwBD)",
        "feeFemale": "₹ 0/-",
        "feeMode": "Online",
    },

    "UPESSC PRT Assistant Teacher Online Form 2026 (12405 Post)": {
        "feeGen": "₹ 1000/-",
        "feeOBC": "₹ 1000/-",
        "feeSC": "₹ 500/-",
        "feeST": "₹ 500/-",
        "feeReserved": "₹ 300/- (PwD)",
        "feeFemale": "As per category",
        "feeMode": "Online",
    },

    "Bihar BTSC Touring Veterinary Officer Online Form 2026": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 100/-",
        "feeST": "₹ 100/-",
        "feeReserved": "₹ 100/-",
        "feeFemale": "₹ 100/-",
        "feeMode": "Online",
    },

    "Bihar BTSC Fishery Extension Officer Online Form 2026": {
        "feeGen": "₹ 100/-",
        "feeOBC": "₹ 100/-",
        "feeSC": "₹ 100/-",
        "feeST": "₹ 100/-",
        "feeReserved": "₹ 100/-",
        "feeFemale": "₹ 100/-",
        "feeMode": "Online",
    },

    "Bank of Baroda SO Online Form 2026 (1100 Posts) – Date Extend": {
        "feeGen": "₹ 850/-",
        "feeOBC": "₹ 850/-",
        "feeSC": "₹ 175/-",
        "feeST": "₹ 175/-",
        "feeReserved": "₹ 175/-",
        "feeFemale": "₹ 175/-",
        "feeMode": "Online",
    },

    "MPESB MP Police Constable Online Form 2026 (7500 Posts)": {
        "feeGen": "₹ 500/-",
        "feeOBC": "₹ 250/-",
        "feeSC": "₹ 250/-",
        "feeST": "₹ 250/-",
        "feeReserved": "₹ 250/-",
        "feeFemale": "₹ 250/-",
        "feeMode": "Online + Portal Charge Extra",
    },

    "IBPS RRB 15th Online Form 2026 (13,706 Posts) – Last Date Today": {
        "feeGen": "₹ 850/-",
        "feeOBC": "₹ 850/-",
        "feeSC": "₹ 175/-",
        "feeST": "₹ 175/-",
        "feeReserved": "₹ 175/-",
        "feeFemale": "₹ 850/-",
        "feeMode": "Online",
    },
}


def write_auto_job_data(items):
    """Write regenerated job metadata used by job.html on every auto-update."""

    data = {}

    for item in items.get("Latest Jobs", []):

        details = extract_job_details(
            item.get("url", "")
        )

        title = item.get("title", "")

        override = FEE_OVERRIDES.get(title)

        if override:
            details.update(override)

        key = (
            urlparse(
                item.get("url", "")
            ).path.strip("/")
            + "/"
        )

        if key.strip("/"):
            data[key] = details

        data[title] = details

    target = BASE / "cp-auto-job-data.js"

    import json

    target.write_text(
        "window.CP_AUTO_JOB_DATA="
        + json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + ";",
        encoding="utf-8",
    )


PINNED_DOCUMENT_SERVICES = [
    {
        "title": "Aadhaar Card Download – Official UIDAI",
        "url": "https://myaadhaar.uidai.gov.in/genricDownloadAadhaar/en",
        "official": "https://myaadhaar.uidai.gov.in/genricDownloadAadhaar/en",
    },
    {
        "title": "Aadhaar Card Correction / Update – Official UIDAI",
        "url": "https://myaadhaar.uidai.gov.in/",
        "official": "https://myaadhaar.uidai.gov.in/",
    },
    {
        "title": "Bihar Residence Certificate – ServicePlus",
        "url": "https://serviceonline.bihar.gov.in/renderApplicationForm.do?serviceId=4630012",
        "official": "https://serviceonline.bihar.gov.in/renderApplicationForm.do?serviceId=4630012",
    },
    {
        "title": "Bihar Caste Certificate – ServicePlus",
        "url": "https://serviceonline.bihar.gov.in/renderApplicationForm.do?serviceId=4650013",
        "official": "https://serviceonline.bihar.gov.in/renderApplicationForm.do?serviceId=4650013",
    },
    {
        "title": "Bihar Income Certificate – ServicePlus",
        "url": "https://serviceonline.bihar.gov.in/",
        "official": "https://serviceonline.bihar.gov.in/",
    },
]


def main():

    items = {}

    for heading, (_, url) in CATEGORIES.items():

        try:

            items[heading] = extract_category(
                ROOT + url,
                heading,
            )

            items[heading] = enrich_official_links(
                items[heading],
                heading,
            )

            if heading == "Admit Cards":
                items[heading] = enrich_admit_cards(
                    items[heading]
                )

            print(
                f"{heading}: "
                f"{len(items[heading])}"
            )

        except Exception as exc:

            print(
                f"WARNING: {heading} source unavailable; "
                f"keeping existing page data: {exc}"
            )

            items[heading] = []

    existing_doc_urls = {
        x.get("url", "")
        for x in items.get(
            "Documents",
            [],
        )
    }

    pinned = [
        dict(x)
        for x in PINNED_DOCUMENT_SERVICES
        if x.get("url")
        not in existing_doc_urls
    ]

    items["Documents"] = (
        pinned
        + items.get(
            "Documents",
            [],
        )
    )

    items = enforce_category_separation(
        items
    )

    primary = sum(
        bool(items.get(k))
        for k in (
            "Latest Jobs",
            "Results",
            "Admit Cards",
        )
    )

    if primary < 2:

        print(
            "WARNING: Source server was unreachable. "
            "No existing page was overwritten."
        )

        return

    write_auto_job_data(
        items
    )

    firsts = [
        items[k][0]["title"].lower()
        for k in (
            "Latest Jobs",
            "Results",
            "Admit Cards",
        )
        if items.get(k)
    ]

    if (
        len(firsts) >= 3
        and len(set(firsts)) == 1
    ):
        raise RuntimeError(
            "Source validation failed: "
            "category lists are identical; "
            "refusing to overwrite."
        )

    update_index(
        items
    )

    update_page(
        "all-jobs.html",
        "jobs",
        items["Latest Jobs"],
    )

    update_page(
        "all-results.html",
        "results",
        items["Results"],
    )

    update_page(
        "all-admit-card.html",
        "admit",
        items["Admit Cards"],
    )

    update_page(
        "all-answer-key.html",
        "answer",
        items["Answer Key"],
    )

    update_page(
        "all-admission.html",
        "admission",
        items["Admission"],
    )

    update_page(
        "all-iti-jobs.html",
        "iti",
        items["10th/ITI Jobs"],
    )

    update_page(
        "all-outsourcing-jobs.html",
        "outsourcing",
        items["Outsourcing Jobs"],
    )

    update_page(
        "all-syllabus.html",
        "syllabus",
        items["Syllabus"],
    )

    update_page(
        "all-documents-verification.html",
        "documents",
        items["Documents"],
    )

    mixed_all = []

    for heading in (
        "Results",
        "Admit Cards",
        "Latest Jobs",
        "Answer Key",
        "Documents",
        "Admission",
        "10th/ITI Jobs",
        "Outsourcing Jobs",
        "Syllabus",
    ):

        kind = CATEGORIES[heading][0]

        for item in items[heading][:10]:

            copy_item = dict(item)

            copy_item["_kind"] = kind

            mixed_all.append(
                copy_item
            )

    update_page(
        "all-latest-update.html",
        "updates",
        mixed_all[:70],
    )

    stamp_update_date()

    print(
        "Computer Prachi category update "
        "completed successfully."
    )


if __name__ == "__main__":
    main()
