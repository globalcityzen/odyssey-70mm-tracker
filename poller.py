"""Multi-chain poller for The Odyssey IMAX 70mm availability.

Reads venues.json, polls AMC / Regal / Cinemark for 70mm showtimes and
sold-out status, writes docs/data.json for the static frontend.

Stdlib only. Per-venue error isolation: one chain hiccup never blanks the site.
Usage: python poller.py [--days N] [--out PATH]
"""

import argparse
import datetime as dt
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")
BASE_HEADERS = [
    ("User-Agent", UA),
    ("Accept-Language", "en-US,en;q=0.9"),
    ("sec-ch-ua", '"Not;A=Brand";v="99", "Chromium";v="139"'),
    ("sec-ch-ua-mobile", "?0"),
    ("sec-ch-ua-platform", '"Windows"'),
]
DOC_HEADERS = BASE_HEADERS + [
    ("Accept", "text/html,application/xhtml+xml,*/*;q=0.8"),
    ("Sec-Fetch-Dest", "document"), ("Sec-Fetch-Mode", "navigate"),
    ("Sec-Fetch-Site", "none"), ("Sec-Fetch-User", "?1"),
    ("Upgrade-Insecure-Requests", "1"),
]

SOLD_OUT, ALMOST_FULL, AVAILABLE = "SOLD_OUT", "ALMOST_FULL", "AVAILABLE"
PAUSE = 0.8  # seconds between requests, per politeness


def opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def fetch(op, url, headers, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=dict(headers))
            return op.open(req, timeout=45).read().decode("utf-8", "ignore")
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 * (attempt + 1))


# ---------------------------------------------------------------- AMC

def poll_amc(venue, dates):
    op = opener()
    shows = []
    url_t = ("https://www.amctheatres.com/movie-theatres/{market}/{slug}"
             "/showtimes/all/{date}/{slug}/all")
    for date in dates:
        html = fetch(op, url_t.format(market=venue["market"], slug=venue["slug"],
                                      date=date), DOC_HEADERS)
        for sec in re.finditer(
                r'id="the-odyssey-\d+-[a-z0-9-]*imax70mm-\d+-attributes".*?</ul>\s*'
                r'<ul[^>]*aria-label="Showtime Group Results"(.*?)</ul>',
                html, re.S):
            for chunk in sec.group(1).split("<li")[1:]:
                t = re.search(r'<time dateTime="([^"]+)">', chunk)
                if not t:
                    continue
                sid_m = re.search(r'id="(\d{6,})"', chunk)
                text = re.sub(r"<[^>]+>", " ", chunk).lower()
                status = (SOLD_OUT if "sold out" in text
                          else ALMOST_FULL if "almost full" in text
                          else AVAILABLE)
                sid = sid_m.group(1) if sid_m else None
                shows.append({
                    "utc": t.group(1), "status": status,
                    "url": (f"https://www.amctheatres.com/showtimes/{sid}" if sid
                            else url_t.format(market=venue["market"],
                                              slug=venue["slug"], date=date)),
                })
        time.sleep(PAUSE)
    return shows


# ---------------------------------------------------------------- Regal

def poll_regal(venues, dates):
    """One API call per date covers every Regal venue (batched theatre codes)."""
    op = opener()
    fetch(op, "https://www.regmovies.com/theatres/" + venues[0]["path"],
          DOC_HEADERS)  # warm the __cf_bm cookie
    xhr = BASE_HEADERS + [
        ("Accept", "application/json, text/plain, */*"),
        ("Sec-Fetch-Dest", "empty"), ("Sec-Fetch-Mode", "cors"),
        ("Sec-Fetch-Site", "same-origin"),
        ("Referer", "https://www.regmovies.com/theatres/" + venues[0]["path"]),
    ]
    by_code = {v["code"]: v for v in venues}
    out = {v["id"]: [] for v in venues}
    codes = ",".join(by_code)
    seen = {v["id"]: set() for v in venues}  # adjacent dates overlap; dedup
    for date in dates:
        mdY = f"{date[5:7]}-{date[8:10]}-{date[0:4]}"
        url = (f"https://www.regmovies.com/api/getShowtimes?theatres={codes}"
               f"&date={mdY}&hoCode=&ignoreCache=false&moviesOnly=false")
        data = json.loads(fetch(op, url, xhr))
        for day in data.get("shows", []):
            venue = by_code.get(day.get("TheatreCode"))
            if not venue:
                continue
            for film in day.get("Film", []):
                if "odyssey" not in film.get("Title", "").lower():
                    continue
                for p in film.get("Performances", []):
                    attrs = p.get("PerformanceAttributes", [])
                    # Colorado Center tags its 70mm engagement as plain "IMAX"
                    is70 = (any("70mm" in a.lower() for a in attrs)
                            or (venue.get("imaxAttrIs70mm")
                                and any(a.upper() == "IMAX" for a in attrs)))
                    if not is70:
                        continue
                    pid = p.get("PerformanceId")
                    if pid in seen[venue["id"]]:
                        continue
                    seen[venue["id"]].add(pid)
                    out[venue["id"]].append({
                        "utc": p.get("UtcShowTime"),
                        "local": p.get("CalendarShowTime"),
                        "status": SOLD_OUT if p.get("StopSales") else AVAILABLE,
                        "url": "https://www.regmovies.com/theatres/" + venue["path"],
                    })
        time.sleep(PAUSE)
    return out


# ---------------------------------------------------------------- Cinemark

def poll_cinemark(venue, dates):
    op = opener()
    fetch(op, f"https://www.cinemark.com/theatres/{venue['path']}", DOC_HEADERS)
    shows = []
    for date in dates:
        # the theatre page ignores ?showDate — the picker XHRs this endpoint
        html = fetch(op, "https://www.cinemark.com/umbraco/surface/Showtimes/"
                         f"GetByTheaterId?theaterId={venue['theaterId']}"
                         f"&showDate={date}", DOC_HEADERS)
        # scope to the Odyssey IMAX 70MM movie block
        for block in html.split('class="showtimeMovieBlock')[1:]:
            if "the-odyssey-imax-70mm" not in block:
                continue
            for m in re.finditer(
                    r'<div class="showtime"[^>]*data-print-type-name="Imax 70mm"[^>]*>\s*'
                    r'(?:<p class="off soldOut"[^>]*>\s*([\d:apm\s]+?)<'
                    r'|<a[^>]*class="showtime-link"[^>]*href="([^"]+)"[^>]*>\s*([\d:apm\s]+?)<)',
                    block):
                sold_time, href, avail_time = m.groups()
                if sold_time:
                    shows.append({
                        "local": f"{date}T{_to24(sold_time.strip())}",
                        "status": SOLD_OUT,
                        "url": f"https://www.cinemark.com/theatres/{venue['path']}",
                    })
                else:
                    st = re.search(r"Showtime=([\d:T-]+)", href)
                    shows.append({
                        "local": st.group(1) if st else f"{date}T{_to24(avail_time.strip())}",
                        "status": AVAILABLE,
                        "url": "https://www.cinemark.com" + href.replace("&amp;", "&"),
                    })
        time.sleep(PAUSE)
    # a date page can show spillover shows from adjacent dates; dedup by local time
    uniq = {}
    for s in shows:
        uniq[s["local"]] = s
    return list(uniq.values())


def _to24(t):
    m = re.match(r"(\d{1,2}):(\d{2})\s*([ap])m?", t, re.I)
    if not m:
        return "00:00:00"
    h, mnt, ap = int(m.group(1)), m.group(2), m.group(3).lower()
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mnt}:00"


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--out", default=os.path.join("docs", "data.json"))
    ap.add_argument("--venues", default="venues.json")
    args = ap.parse_args()

    with open(args.venues, encoding="utf-8-sig") as f:
        venues = json.load(f)["venues"]
    today = dt.date.today()
    dates = [(today + dt.timedelta(days=i)).isoformat() for i in range(args.days)]

    results = []
    regal_venues = [v for v in venues if v["chain"] == "regal"]
    regal_shows, regal_err = {}, None
    try:
        regal_shows = poll_regal(regal_venues, dates)
    except Exception as e:
        regal_err = f"{type(e).__name__}: {e}"

    for v in venues:
        entry = {k: v[k] for k in ("id", "chain", "name", "city", "state", "region", "tz")}
        entry["buyUrl"] = v.get("url") or ""
        try:
            if v["chain"] == "amc":
                entry["shows"] = poll_amc(v, dates)
                entry["buyUrl"] = ("https://www.amctheatres.com/movie-theatres/"
                                   f"{v['market']}/{v['slug']}")
            elif v["chain"] == "regal":
                if regal_err:
                    raise RuntimeError(regal_err)
                entry["shows"] = regal_shows.get(v["id"], [])
                entry["buyUrl"] = "https://www.regmovies.com/theatres/" + v["path"]
            elif v["chain"] == "cinemark":
                entry["shows"] = poll_cinemark(v, dates)
                entry["buyUrl"] = "https://www.cinemark.com/theatres/" + v["path"]
            else:
                entry["shows"] = None  # independent: listed, not yet tracked
        except Exception as e:
            entry["shows"] = []
            entry["error"] = f"{type(e).__name__}: {e}"
        results.append(entry)
        n = len(entry["shows"]) if entry["shows"] else 0
        print(f"  {v['id']:26s} shows={n}" + (f"  ERROR {entry.get('error')}" if entry.get("error") else ""))

    tracked = [r for r in results if r["shows"] is not None]
    payload = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "horizonDays": args.days,
        "venues": results,
        "stats": {
            "trackedVenues": len(tracked),
            "totalShows": sum(len(r["shows"]) for r in tracked),
            "soldOut": sum(1 for r in tracked for s in r["shows"] if s["status"] == SOLD_OUT),
            "errors": sum(1 for r in results if r.get("error")),
        },
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"wrote {args.out}: {payload['stats']}")
    return 0 if payload["stats"]["errors"] < len(tracked) else 1


if __name__ == "__main__":
    sys.exit(main())
