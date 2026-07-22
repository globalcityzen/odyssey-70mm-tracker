"""Odyssey IMAX 70mm watcher — SF Bay Area (AMC Metreon 16 + Regal Hacienda Crossings).

Polls both venues for IMAX 70mm showtimes of The Odyssey, diffs against saved
state, and prints alert lines for:
  * NEW showtimes appearing (new weeks going on sale)
  * seat RETURNS (a show leaving SOLD_OUT)

Stdlib only. Exit code 2 = alerts found, 0 = no change, 1 = error.
Usage: python watcher.py [--days N] [--state PATH]
"""

import argparse
import datetime as dt
import http.cookiejar
import json
import re
import sys
import time
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

CHROME_HEADERS = [
    ("User-Agent", UA),
    ("Accept-Language", "en-US,en;q=0.9"),
    ("sec-ch-ua", '"Not;A=Brand";v="99", "Chromium";v="139"'),
    ("sec-ch-ua-mobile", "?0"),
    ("sec-ch-ua-platform", '"Windows"'),
]

AMC_URL = ("https://www.amctheatres.com/movie-theatres/san-francisco/"
           "amc-metreon-16/showtimes/all/{date}/amc-metreon-16/all")
REGAL_PAGE = "https://www.regmovies.com/theatres/regal-hacienda-crossings-0347"
REGAL_API = ("https://www.regmovies.com/api/getShowtimes?theatres=0347"
             "&date={date}&hoCode=&ignoreCache=false&moviesOnly=false")

SOLD_OUT, ALMOST_FULL, AVAILABLE = "SOLD_OUT", "ALMOST_FULL", "AVAILABLE"


def make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def fetch(opener, url, extra_headers, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=dict(CHROME_HEADERS + extra_headers))
            return opener.open(req, timeout=45).read().decode("utf-8", "ignore")
        except Exception:
            if attempt == retries:
                raise
            time.sleep(3 * (attempt + 1))


DOC_HEADERS = [
    ("Accept", "text/html,application/xhtml+xml,*/*;q=0.8"),
    ("Sec-Fetch-Dest", "document"), ("Sec-Fetch-Mode", "navigate"),
    ("Sec-Fetch-Site", "none"), ("Sec-Fetch-User", "?1"),
    ("Upgrade-Insecure-Requests", "1"),
]
XHR_HEADERS = [
    ("Accept", "application/json, text/plain, */*"),
    ("Sec-Fetch-Dest", "empty"), ("Sec-Fetch-Mode", "cors"),
    ("Sec-Fetch-Site", "same-origin"),
    ("Referer", REGAL_PAGE),
]


def check_amc(dates):
    """Scrape Metreon showtime pages; yield (key, info) for Odyssey IMAX 70mm shows."""
    opener = make_opener()
    shows = {}
    for date in dates:
        html = fetch(opener, AMC_URL.format(date=date), DOC_HEADERS)
        # The 70mm block: everything between the imax70mm attributes list and the
        # next format section. Anchor ids are the showtime ids.
        for sec in re.finditer(
                r'id="the-odyssey-\d+-amc-metreon-16-imax70mm-\d+-attributes".*?</ul>\s*<ul[^>]*aria-label="Showtime Group Results"(.*?)</ul>',
                html, re.S):
            body = sec.group(1)
            # Element-agnostic: sold-out shows may render as disabled buttons
            # rather than anchors, so match any <li> chunk containing a <time>.
            for chunk in body.split("<li")[1:]:
                t = re.search(r'<time dateTime="([^"]+)">', chunk)
                if not t:
                    continue
                when = t.group(1)
                sid_m = re.search(r'id="(\d{6,})"', chunk)
                sid = sid_m.group(1) if sid_m else None
                text = re.sub(r"<[^>]+>", " ", chunk).lower()
                if "sold out" in text:
                    status = SOLD_OUT
                elif "almost full" in text:
                    status = ALMOST_FULL
                else:
                    status = AVAILABLE
                key = f"amc-metreon|{sid or when}"
                shows[key] = {
                    "venue": "AMC Metreon 16 (SF)", "utc": when,
                    "date": date, "status": status,
                    "url": (f"https://www.amctheatres.com/showtimes/{sid}"
                            if sid else AMC_URL.format(date=date)),
                }
        time.sleep(1.5)  # be polite
    return shows


def check_regal(dates):
    """Regal JSON API; warm the __cf_bm cookie on the page first."""
    opener = make_opener()
    fetch(opener, REGAL_PAGE, DOC_HEADERS)  # cookie warm-up
    shows = {}
    for date in dates:
        mdY = f"{date[5:7]}-{date[8:10]}-{date[0:4]}"
        data = json.loads(fetch(opener, REGAL_API.format(date=mdY), XHR_HEADERS))
        for day in data.get("shows", []):
            for film in day.get("Film", []):
                if "odyssey" not in film.get("Title", "").lower():
                    continue
                for p in film.get("Performances", []):
                    attrs = p.get("PerformanceAttributes", [])
                    if not any("70mm" in a.lower() for a in attrs):
                        continue
                    status = SOLD_OUT if p.get("StopSales") else AVAILABLE
                    shows[f"regal-hacienda|{p['PerformanceId']}"] = {
                        "venue": "Regal Hacienda Crossings (Dublin)",
                        "utc": p.get("UtcShowTime", ""),
                        "local": p.get("CalendarShowTime", ""),
                        "date": date, "status": status,
                        "url": REGAL_PAGE,
                    }
        time.sleep(1.5)
    return shows


def fmt(info):
    when = info.get("local") or info.get("utc", "?")
    return f"{info['venue']}  {when}  [{info['status']}]  {info['url']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--state", default="state.json")
    args = ap.parse_args()

    today = dt.date.today()
    dates = [(today + dt.timedelta(days=i)).isoformat() for i in range(args.days)]

    current = {}
    errors = []
    for name, checker in [("amc", check_amc), ("regal", check_regal)]:
        try:
            current.update(checker(dates))
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")

    if not current and errors:
        print("ERROR both sources failed:", "; ".join(errors))
        return 1

    try:
        with open(args.state, encoding="utf-8-sig") as f:
            previous = json.load(f)
    except FileNotFoundError:
        previous = None

    alerts = []
    if previous is not None:
        for key, info in current.items():
            old = previous.get(key)
            if old is None:
                if info["status"] != SOLD_OUT:  # a new-but-full show isn't actionable
                    alerts.append(f"NEW SHOWTIME: {fmt(info)}")
            elif old["status"] == SOLD_OUT and info["status"] != SOLD_OUT:
                alerts.append(f"SEATS RETURNED: {fmt(info)}")

    # merge so a venue erroring out doesn't wipe its shows (avoids false NEW next run)
    merged = dict(previous or {})
    merged.update(current)
    with open(args.state, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=1)

    n_sold = sum(1 for v in current.values() if v["status"] == SOLD_OUT)
    print(f"checked {len(current)} 70mm showtimes over {args.days} days "
          f"({n_sold} sold out){'; errors: ' + '; '.join(errors) if errors else ''}")
    if previous is None:
        print("state seeded (first run, no alerts)")
        return 0
    for a in alerts:
        print(a)
    return 2 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
