import sys
import urllib.request
import xml.etree.ElementTree as ET

url = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 6

req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as r:
    data = r.read()

root = ET.fromstring(data)
items = root.findall(".//item")[:limit]
for it in items:
    title = (it.findtext("title") or "").strip()
    link = (it.findtext("link") or "").strip()
    print(f"{title}\t{link}")
