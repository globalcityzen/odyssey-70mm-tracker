import urllib.request, http.cookiejar, re, json, time, datetime as dt
V=json.load(open(r"C:\Users\rajac\ai-playground\odyssey-70mm-watcher\venues.json",encoding="utf-8-sig"))["venues"]
def opener():
    cj=http.cookiejar.CookieJar()
    op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders=[("User-Agent","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"),
     ("Accept","text/html,*/*;q=0.8"),("Accept-Language","en-US,en;q=0.9"),
     ("Sec-Fetch-Dest","document"),("Sec-Fetch-Mode","navigate"),("Sec-Fetch-Site","none"),("Sec-Fetch-User","?1"),
     ("Upgrade-Insecure-Requests","1")]
    return op
date=(dt.date.today()+dt.timedelta(days=3)).isoformat()  # Friday
for v in V:
    if v["chain"]=="independent": continue
    op=opener()
    try:
        if v["chain"]=="amc":
            u=f"https://www.amctheatres.com/movie-theatres/{v['market']}/{v['slug']}/showtimes/all/{date}/{v['slug']}/all"
            h=op.open(u,timeout=45).read().decode("utf-8","ignore")
            n=len(re.findall(r'imax70mm-\d+-attributes',h))
            ok = "odyssey" in h.lower()
            print(f"{v['id']:26s} {'OK' if ok else '??'}  70mm-sections={n}  len={len(h)}")
        elif v["chain"]=="regal":
            u=f"https://www.regmovies.com/theatres/{v['path']}"
            h=op.open(u,timeout=45).read().decode("utf-8","ignore")
            d=json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',h,re.S).group(1))
            perfs=[p for day in d["props"]["pageProps"]["showtimes"] for f in day["Film"] if "odyssey" in f["Title"].lower() for p in f["Performances"] if any("70mm" in a.lower() for a in p["PerformanceAttributes"])]
            print(f"{v['id']:26s} OK  70mm-today={len(perfs)}  sold={sum(1 for p in perfs if p['StopSales'])}")
        elif v["chain"]=="cinemark":
            u=f"https://www.cinemark.com/theatres/{v['path']}?showDate={date}"
            h=op.open(u,timeout=45).read().decode("utf-8","ignore")
            n=h.count('data-print-type-name="Imax 70mm"')
            sold=len(re.findall(r'data-print-type-name="Imax 70mm"[^>]*>\s*<p class="off soldOut"',h))
            print(f"{v['id']:26s} {'OK' if n else '??'}  70mm-times={n}  sold={sold}")
    except Exception as e:
        print(f"{v['id']:26s} ERROR {type(e).__name__} {getattr(e,'code','')}")
    time.sleep(1.2)
