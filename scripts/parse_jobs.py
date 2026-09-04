import sys
import json
import os
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from job_filters import matches_keywords, is_senior, location_ok

HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def from_remoteok():
    try:
        data = fetch_json("https://remoteok.com/api")
    except Exception:
        return
    for job in data:
        if not isinstance(job, dict) or "position" not in job:
            continue
        position = job.get("position", "").strip()
        company = job.get("company", "").strip()
        location = job.get("location", "").strip() or "Remote"
        link = job.get("url", "")
        hits = matches_keywords(position + " " + " ".join(job.get("tags") or []))
        if not hits or is_senior(position) or not location_ok(location):
            continue
        yield (position, company, location, link, ", ".join(hits[:3]), "RemoteOK")


def from_arbeitnow():
    try:
        data = fetch_json("https://www.arbeitnow.com/api/job-board-api")
    except Exception:
        return
    for job in data.get("data", []):
        title = job.get("title", "").strip()
        if not job.get("remote"):
            continue
        hits = matches_keywords(title + " " + " ".join(job.get("tags") or []))
        if not hits or is_senior(title):
            continue
        company = job.get("company_name", "").strip()
        link = job.get("url", "")
        yield (title, company, "Remote", link, ", ".join(hits[:3]), "Arbeitnow")


def from_himalayas(limit=100):
    try:
        data = fetch_json(f"https://himalayas.app/jobs/api?limit={limit}")
    except Exception:
        return
    for job in data.get("jobs", []):
        title = job.get("title", "").strip()
        seniority = [s.lower() for s in (job.get("seniority") or [])]
        if any(s in ("senior", "lead", "staff", "director", "executive") for s in seniority):
            continue
        restrictions = job.get("locationRestrictions") or []
        if restrictions and not any(
            r.lower() in ("spain", "europe", "emea", "worldwide") for r in restrictions
        ):
            continue
        hits = matches_keywords(title + " " + " ".join(job.get("categories") or []))
        if not hits:
            continue
        company = job.get("companyName", "").strip()
        link = job.get("applicationLink", "")
        yield (title, company, "Remote", link, ", ".join(hits[:3]), "Himalayas")


limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
count = 0
for source_fn in (from_remoteok, from_arbeitnow, from_himalayas):
    for position, company, location, link, matched, source in source_fn():
        print(f"{position}\t{company}\t{location}\t{link}\t{matched}\t{source}")
        count += 1
        if count >= limit:
            sys.exit(0)
