import imaplib
import email
import os
import sys
import re
from email.header import decode_header
from email.utils import parseaddr
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from job_filters import matches_keywords, is_senior, location_ok

IMAP_HOST = "imap.gmail.com"
IMAP_USER = "tu_correo@gmail.com"

with open(os.path.expanduser("~/.imap_pass")) as f:
    IMAP_PASS = f.read().strip()

STATE_FILE = sys.argv[1] if len(sys.argv) > 1 else "last_uid.txt"

LINK_LINE_RE = re.compile(r"Ver anuncio de empleo:\s*(\S+)")
JOB_LINK_RE = re.compile(r"(https://[a-z.]*linkedin\.com/(?:comm/)?jobs/view/\d+)")
NOISE_SUBSTRINGS = [
    "esta empresa busca personal",
    "nuevos empleos coinciden",
    "tu alerta de empleo",
]


def parse_linkedin_jobs(body):
    jobs = []
    prev_end = 0
    for m in LINK_LINE_RE.finditer(body):
        chunk = body[prev_end:m.start()]
        prev_end = m.end()
        lines = [l.strip() for l in chunk.splitlines()]
        lines = [l for l in lines if l and not re.match(r"^-{3,}$", l)]
        lines = [l for l in lines if not any(n in l.lower() for n in NOISE_SUBSTRINGS)]
        if len(lines) < 3:
            continue
        title, company, location = lines[-3], lines[-2], lines[-1]
        raw_link = m.group(1)
        link_match = JOB_LINK_RE.search(raw_link)
        link = link_match.group(1) + "/" if link_match else raw_link
        jobs.append((title, company, location, link))
    return jobs


class _MonsterLinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_link = False
        self.current_href = None
        self.current_text = []
        self.results = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if "click.monster.com" in href:
                self.in_link = True
                self.current_href = href
                self.current_text = []

    def handle_data(self, data):
        if self.in_link:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.in_link:
            text = re.sub(r"\s+", " ", "".join(self.current_text)).strip()
            if text:
                self.results.append((text, self.current_href))
            self.in_link = False


def parse_monster_jobs(html):
    parser = _MonsterLinkExtractor()
    parser.feed(html)
    jobs = []
    pending_title = None
    for text, href in parser.results:
        if text.strip().upper() == "VIEW JOB" and pending_title:
            jobs.append((pending_title, "", "", href))
            pending_title = None
        elif len(text) >= 8 and text[:1].isupper():
            pending_title = text
    return jobs


class _TextExtractor(HTMLParser):
    """Strips tags for generic HTML emails, skipping <style>/<script> content."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.skip = True

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html):
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def decode_str(s):
    if not s:
        return ""
    parts = decode_header(s)
    out = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            out += part.decode(enc or "utf-8", errors="ignore")
        else:
            out += part
    return out


def get_part(msg, content_type):
    for part in msg.walk():
        if part.get_content_type() == content_type:
            try:
                text = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="ignore"
                )
                if text.strip():
                    return text
            except Exception:
                continue
    return ""


def get_body_text(msg):
    if not msg.is_multipart():
        try:
            text = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="ignore"
            )
        except Exception:
            return ""
        return html_to_text(text) if msg.get_content_type() == "text/html" else text
    plain = get_part(msg, "text/plain")
    if plain:
        return plain
    html = get_part(msg, "text/html")
    return html_to_text(html) if html else ""


m = imaplib.IMAP4_SSL(IMAP_HOST)
m.login(IMAP_USER, IMAP_PASS)
m.select("INBOX", readonly=True)

try:
    with open(STATE_FILE) as f:
        last_uid = int(f.read().strip())
except (FileNotFoundError, ValueError):
    last_uid = 0

status, data = m.uid("search", None, "ALL")
uids = [int(u) for u in data[0].split()] if data[0] else []

if last_uid == 0:
    if uids:
        with open(STATE_FILE, "w") as f:
            f.write(str(max(uids)))
    m.logout()
    sys.exit(0)

new_uids = sorted(u for u in uids if u > last_uid)

for uid in new_uids:
    status, msg_data = m.uid("fetch", str(uid), "(BODY.PEEK[])")
    if not msg_data or not msg_data[0]:
        continue
    raw = msg_data[0][1]
    msg = email.message_from_bytes(raw)
    sender = decode_str(msg.get("From", ""))
    subject = decode_str(msg.get("Subject", ""))
    sender_lower = sender.lower()

    if "linkedin.com" in sender_lower:
        body = get_body_text(msg)
        for title, company, location, link in parse_linkedin_jobs(body):
            hits = matches_keywords(title)
            if not hits or is_senior(title) or not location_ok(location):
                continue
            print(f"LINKEDIN\t{title}\t{company}\t{location}\t{link}\t{', '.join(hits[:3])}")
    elif "monster.com" in sender_lower:
        # Monster ya filtra por ubicacion en la propia alerta configurada
        # (ver Subject, p.ej. "AI & Software Engineer, Madrid, Madrid"),
        # asi que aqui solo comprobamos palabras clave y seniority.
        html = get_part(msg, "text/html")
        for title, company, location, link in parse_monster_jobs(html):
            hits = matches_keywords(title)
            if not hits or is_senior(title):
                continue
            print(f"MONSTER\t{title}\t{company}\t{location}\t{link}\t{', '.join(hits[:3])}")
    else:
        body = get_body_text(msg)
        snippet = re.sub(r"\s+", " ", body).strip()[:300]
        # msgid/from_addr: para poder responder de verdad al correo original
        # (threading + destinatario), no solo mostrarlo
        msgid = decode_str(msg.get("Message-ID", "")).replace("\t", " ").replace("\n", " ")
        from_addr = parseaddr(sender)[1]
        print(f"OTHER\t{sender}\t{subject}\t{snippet}\t{msgid}\t{from_addr}")

if new_uids:
    with open(STATE_FILE, "w") as f:
        f.write(str(max(new_uids)))

m.logout()
