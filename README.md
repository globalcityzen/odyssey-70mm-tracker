# The Odyssey — IMAX 70mm Ticket Tracker

Live seat availability for every US theater projecting Christopher Nolan's
*The Odyssey* in IMAX 15/70mm film — the format with ~25 capable screens in
the country and showtimes that sell out in minutes.

**Site:** https://globalcityzen.github.io/odyssey-70mm-tracker/

Sold-out shows get seat returns all the time. The tracker polls every venue's
public showtime pages every ~15 minutes and shows, per showtime, whether seats
are currently bookable — so you can catch a return instead of paying a scalper.

## How it works

- [`poller.py`](poller.py) — stdlib-only Python. Chain adapters:
  - **AMC** (4 venues): server-rendered showtime pages, per-date
  - **Regal** (8 venues): `getShowtimes` JSON API, `StopSales` flag, batched theatre codes
  - **Cinemark** (4 venues): `GetByTheaterId` showtimes fragment, `soldOut` markup
  - 9 independent venues are listed with box-office links (adapters welcome — PRs open)
- [`venues.json`](venues.json) — the registry of all 25 US 70mm venues
- [`docs/`](docs/) — static frontend (GitHub Pages) reading `docs/data.json`
- [`.github/workflows/poll.yml`](.github/workflows/poll.yml) — the 15-minute cron

## Notes

- Not affiliated with any theater chain, IMAX, or Universal Pictures.
- Data comes from public showtime pages; polling is rate-limited and polite
  (~1 request/second, ~100 requests per cycle across all venues).
- Availability can lag reality by a few minutes; always confirm at the box office link.

🤖 Built with [Claude Code](https://claude.com/claude-code)
