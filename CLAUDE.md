# UKBoardgames — "Buy in the UK?" Advisor

One-off personal tool. Ranks every board game on Zatu's catalogue worth buying during a UK trip:
good games, hard to get or pricier in France, ideally coop/party, ideally low-language-dependence.
Full spec: `docs/spec.md` — read it before implementing anything, it has the pipeline, scoring
formulas, config schema, and fixture data to code against offline.

## Workflow

- Solo side project. Work directly on `main`, push directly — no PRs, no feature branches.

## Network reality in this coding environment

Verified by direct test: this sandbox's network policy **blocks Zatu, BGG, Philibert, and
1jour-1jeu.com outright** (gateway 403 on CONNECT) — not flaky connectivity, a fixed policy. PyPI/npm/
GitHub work fine, so installing deps and pushing code is unaffected. Practical upshot: write and
unit-test Stages 0–2/6/7 here against fixtures (`docs/spec.md` §11 and `tests/fixtures/`); the
live-fetching stages (0/3/4/5 hitting real endpoints) run via **GitHub Actions** instead (see below) —
GitHub-hosted runners aren't behind this restriction. Don't waste time re-probing this in-session;
re-check only if the environment's network policy changes.

## Delivery: GitHub Actions does the real fetching

Decided: GitHub Actions runners do all live internet work (they aren't network-restricted the way this
coding sandbox is); this coding environment only ever writes code and unit tests against fixtures.
- `.github/workflows/harvest-zatu.yml` — Stage 0. `workflow_dispatch` + weekly cron. Runs
  `scripts/harvest_zatu.py`, which verifies GBP currency first (aborts loudly if not GBP), harvests +
  light-filters the catalogue, and commits `data/zatu_products.json` straight to `main` (solo project,
  no PR needed).
- `.github/workflows/tests.yml` — runs `pytest` against `tests/fixtures/` on every push to `main`.
- Later stages (3/4/5, then Stage 7 render) should follow the same pattern: real fetching + commit/
  deploy happens in a workflow, not in this session. Stage 7's output is a static HTML file, a natural
  fit for GitHub Pages once the pipeline reaches that stage.

## Pipeline (see docs/spec.md §2-3 for full detail)

```
Stage 0  Zatu JSON harvest      /collections/top-5000-board-games/products.json (Shopify, public)
Stage 1  Board-game filter      light cleanup, Stage 0 is already game-scoped
Stage 2  BGG bulk match+gate    offline match vs pre-downloaded bg_ranks.csv, no network
Stage 3  BGG enrich             thing?id=... + Bearer token (mechanics, language, FR edition)
Stage 4  Zatu detail            price/stock/EAN, mostly already in Stage 0's JSON
Stage 5  Philibert lookup       EAN search first, title fallback; FR availability + price
Stage 6  Scoring                advantage + quality + genre + language = composite
Stage 7  Static HTML output     sortable table, full result set, source links
```

## Key design rules

- **Zatu is the universe** — a game not sold by Zatu is out of scope.
- **Precision over recall in matching**: ambiguous matches are dropped (`dropped.csv`), never
  surfaced for manual review — thousands of candidates make per-game confirmation impossible.
- **No fixed output cutoff** — every game passing the quality gate with a genuine UK advantage
  appears in the ranked table; the person drills down as far as they want.
- **Cheap wide pass, expensive narrow pass**: filter for free (Zatu JSON + local BGG CSV) before
  making per-page HTTP calls (BGG `thing`, Philibert) on the surviving few hundred.
- Price is the *weakest* signal (max 25 pts) — availability/no-FR-edition matters more.

## Data sources & gotchas

- **BGG**: `thing`/`search` need a registered app + `Authorization: Bearer <token>` (register at
  boardgamegeek.com/applications — approval takes a week+). Bulk ranked CSV
  (`bg_ranks.csv`) needs no token — download by hand once, logged into a browser, use it for
  Stage 2. Max 20 ids/call, can return HTTP 202 (poll w/ backoff), 5s courtesy rate limit.
  Fallback if no token: scrape public game pages (mechanics/language/versions are in plain HTML).
- **Zatu**: Shopify. Public `/products.json` and `/collections/<handle>/products.json`, no auth.
  **Currency:** use **bare** paths (`https://zatu.com/products/<handle>`, no locale prefix) —
  confirmed live, this returns GBP directly. A locale-prefixed URL (`/en-us/...`) returned USD in
  the original spec investigation, and a guessed `/en-gb/` prefix turned out to be a 404 (not a
  real route on this store) — the first harvest run failed on that. Still assert
  currency == GBP once per harvest (`verify_gbp_currency` in `sources/zatu.py`) before trusting
  any price, since this is exactly the kind of storefront behaviour that can change silently.
  Price itself is solid — spot-checked against a manual browser price and matched exactly.
  **No EAN, no reliable stock from the *bulk* endpoint**: confirmed on the full first harvest (4178
  products) — `barcode` is `null` on every single variant, no exceptions, and so is
  `inventory_quantity`; `available` reports `true` for all 4178 products, which with no inventory
  number to cross-check is not a trustworthy stock signal. So Stage 2 matching has to run on title
  (not EAN — that tier just won't fire from the bulk endpoint). **But the per-product endpoint has
  what the bulk one is missing** — confirmed live via `scripts/probe_zatu_detail.py`
  (2026-08-10): `GET /products/<handle>.json` (singular `product` key) returns a real, populated
  `barcode` for the same products the bulk harvest showed `null` for (e.g. Brass: Birmingham:
  `9781988884042`), plus a `price_currency` field confirmed `"GBP"` on all three sampled products.
  `sources/zatu.py` has this wired up: `fetch_product_detail`/`fetch_product_ean` for per-product
  EAN (normalizes 12-digit UPC-A to EAN-13 via zero-pad), and `verify_gbp_currency` now tries
  `price_currency` first before falling back to the proven `og:price:currency` meta-tag check.
  These are Stage 4 tools — one HTTP request per game, meant for the survivors of Stage 2's match,
  not the whole catalogue. Real per-product availability still needs a separate per-product page
  fetch (`fetch_stock_status`, parses `IN_STOCK`/`OUT_OF_STOCK`/`BACK_ORDER`/`PREORDER`/`UNKNOWN`
  from rendered text, spec §11.1) since neither JSON endpoint carries a trustworthy stock signal.
  **Category filter**: `product_type` cleanly separates the catalogue
  (`Board Games`: 4069, `Accessories`: 81, `Miniatures`/`Books`/`Puzzles`/`Trading Card Games`: 28
  total) — `filters.py` now drops `product_type == "Accessories"` outright (zero ambiguity) but
  leaves the other non-"Board Games" types alone, since Stage 2's BGG match is the real gate and
  dropping them here would be a pure recall risk with no upside. **Coop/party**: `tags` substring
  match (`"cooperat"` / `"party"`, case-insensitive) hits 338/286 of the 4178 products — exposed
  as `ZatuProduct.is_coop`/`.is_party`, still a bonus signal per spec, not a substitute for BGG's
  own mechanic data in Stage 3.
- **Philibert**: PrestaShop, no bulk export — needs page fetches. EAN is in a labeled `EAN` field
  under "Fiche technique" (authoritative) and often in the URL (`...-<ean13>.html`, fast
  pre-filter). `Langue(s)` field is the primary FR-language signal. Ignore `product.oos` /
  `product.declinaisons` strings seen in cross-sell widgets — unrendered template leakage, not data.

## Stage 2 — offline BGG match (done, run against the real data)

`sources/bgg.py` (CSV loader), `match.py` (normalization + confidence cascade), `score.py`
(quality gate/score, spec §5.1), `scripts/match_bgg.py` (driver) — all offline, no network, safe
to run in this sandbox unlike Stages 0/3/4/5. `data/bg_ranks.csv` (179,794 games, real BGG dump
dated 2026-08-09, user-provided — no token needed for this file, only Stage 3's `thing`/`search`
calls need that, still pending) is committed; the real match has been run.

- **Real result**: 4178 Zatu products → 140,261 base games after dropping BGG expansions → **576
  survivors** (matched + passed the quality gate). Of the 3602 dropped: 2036 no BGG match at all,
  1273 matched but failed the quality gate, 264 ambiguous exact matches + 25 ambiguous prefix
  matches (multiple BGG entries — usually base/Big Box/expansion editions, e.g. Carcassonne,
  Everdell, Dominion 2nd Edition — share the same normalized title or prefix; Zatu gives no
  reliable year to disambiguate, so these are correctly dropped per spec P2 rather than guessed),
  4 blocked by the digit-conflict veto. Outputs: `data/matched_games.json` (survivors) and
  `data/dropped.csv` (with reasons, for skimming).
- **Prefix-match tier added** (+18 net survivors over the first run): after exact and fuzzy both
  fail, `BggIndex` now checks whether the query is a unique word-boundary prefix of exactly one
  BGG title — e.g. Zatu's plain "Five Tribes" against BGG's actual title "Five Tribes: The Djinns
  of Naqala", or "Sub Terra II (Core Game)" against "Sub Terra II: Inferno's Edge" (previously
  unmatchable — fuzzy scoring favored the *unrelated* shorter "Sub Terra"/"Sub Terra: Collector's
  Edition" over the correct sequel, since the query had no subtitle to compare against). Purely
  additive by construction: only tried when fuzzy already returned nothing, so it can only add
  matches, never override or regress an existing fuzzy decision. Uses a sorted-list binary search
  (`bisect`), not a linear scan, so it adds negligible runtime. Still drops the ambiguous case
  (e.g. "Suspects" is a prefix of 14 different "Suspects: <subtitle>" BGG entries) rather than
  guessing. All 19 real prefix-tier survivors manually spot-checked against the actual matched
  output — no false positives found.
- **Fixed a real noise-stripping bug found the same way**: `"core"` used to be stripped as a bare
  word (originally added for "Spirit Island (Core Game)"), which silently ate the word out of
  "Company of Heroes: 2nd Edition **Core Set**" — a real BGG product-line term, not marketing
  filler. Now only the "core game" phrase is stripped, not "core" alone.
- **Fuzzy match tuning**: `config.yaml`'s `matching.fuzzy_threshold`/`min_score_gap` (90/5) were
  picked from empirical rapidfuzz testing, not guessed — `token_sort_ratio` (not `WRatio`, which
  scores an expansion's title against its own base game at exactly 90.0 due to partial-ratio
  weighting) cleanly separates genuine near-duplicates (~87-96) from false positives (~62-67).
  `match.py`'s digit-conflict veto catches the other real false-positive class a plain scorer
  misses: "Pandemic Legacy: Season 1" vs "Season 2" score ~96% similar despite being different
  games — any query/candidate pair where both sides have digit tokens that differ is rejected
  regardless of fuzzy score.
- **`normalize_title` fixes found by running against the real 4178×179,794 match, not fixture
  data**: (1) HTML entities leak through unescaped on 8 real Zatu titles (e.g. `"Heroes of Land,
  Air &amp; Sea"`) — now run through `html.unescape()` first. (2) BGG writes some titles with a
  thousands-separator comma (463 entries, mostly "Warhammer 40,000" variants) that Zatu's
  listings never do — general punctuation stripping turned `"40,000"` into two digit tokens
  instead of one, spuriously tripping the digit-conflict veto; commas between digits are now
  removed before tokenizing. (3) 18 real Zatu titles carry a trailing `"(2013)"`-style
  release-year annotation with no BGG counterpart — stripped as noise now, anchored so it can't
  eat a year that's actually part of the game's name (e.g. "The Great Fire of London 1666").
  Each fix is backed by a real before/after example found in the actual matched output, not just
  a hypothetical.
- **Spec §5.1's worked example is slightly off**: its own formula, given its own numbers (8.4
  average, 60 votes, M=100, prior=6.5), computes shrunk=7.2125 — not the "~7.7" the prose
  estimates. Implemented the literal formula (confirmed correct via `score.py`'s tests), not the
  prose approximation.
- **Runtime**: ~2m15s for the full match (4178 × 140,261 fuzzy comparisons in the worst case,
  pure Python loop over `rapidfuzz.process.extract`). Acceptable for a weekly/on-demand personal
  run; would be worth batching via `rapidfuzz.process.cdist` if this ever needs to run more often.

## Tech

Python: `requests`, `beautifulsoup4`/`lxml`, `rapidfuzz`, `pandas`, `jinja2`. SQLite cache keyed by
source+id (incremental re-runs, resumable). Adapters behind a common interface:
`sources/{zatu,philibert,bgg}.py`, `match.py`, `score.py`, `render.py`. All tunable weights/thresholds
live in one YAML config (docs/spec.md §10) — re-scoring never needs re-scraping or code changes.

## Build order

1. Register BGG app + download `bg_ranks.csv` (do this first — token approval is slow). **App
   registered, token still pending. `data/bg_ranks.csv` provided by the user and committed.**
2. Zatu JSON harvest + offline match/quality-gate/score against the CSV → first usable ranked
   list. **Done. 558 survivors from 4178 Zatu products × 140,261 BGG base games — see the Stage 2
   section above for the breakdown.**
3. BGG enrich (best-effort, decoupled — don't block the pipeline if the token isn't ready yet).
   **Next up — still blocked on the token, so start with the public-game-page HTML fallback
   (spec §0.1/§3 Stage 3) rather than waiting.**
4. Philibert adapter (EAN first, title fallback).
5. Fill any Zatu detail gaps, then HTML render.
