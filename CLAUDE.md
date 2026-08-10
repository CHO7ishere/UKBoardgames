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
- **Philibert**: PrestaShop (`philibertnet.com` — note: **not** `philibert.net`, a mistake that
  cost a whole probe round). No bulk export or JSON API; a bulk category-page browse (mirroring
  Zatu's Stage 0) was tried and ruled out — the board-games category alone has **12,812
  products**, and its pagination doesn't respond to any guessed query param (`?page=`, `?p=`,
  `#/page-N`), same as the header search — likely JS-driven. **Real working search, confirmed
  live via `scripts/probe_philibert.py` (7 rounds) and a user-supplied browser URL**:
  `GET /fr/recherche?search_query=<query>` — not `s=` (an early guess), and unreachable without
  the `/fr/` locale prefix every real route on this site uses. EAN search is precise: a real EAN
  returns exactly one product link, a garbage EAN-shaped query returns zero. **A garbage TEXT
  query does not reliably return zero** — Philibert's search falls back to unrelated "you might
  like" results rather than a clean empty page, so `search_by_title` fuzzy-filters candidates
  itself (reusing `match.py`'s `normalize_title`) rather than trusting "any results = found".
  Product data confirmed via `li.product-features__item` → `.product-features__name` label +
  value (EAN, Langue(s), Editeur all verified against the real page). Ignore `product.oos` /
  `product.declinaisons` strings seen in cross-sell widgets — unrendered template leakage, not
  data; confirmed live that "Indisponible" text on a real product page was this exact leakage
  (an unrelated accessory's stock state), not the primary product's own. **Stock container
  confirmed live**: `.product-actions` matched on 5/5 real product URLs sampled from the actual
  Stage 5 run and reliably contains the primary product's own "Ajouter au panier" text, not
  cross-sell noise — `_classify_stock` uses it as the primary selector. **Still genuinely open**:
  the real Stage 5 run found 0 of 381 Philibert-listed survivors out of stock — plausible on its
  own (Philibert's stock depth), and the 5 spot-checked samples were all confirmed genuinely
  in-stock, but a real out-of-stock primary product still hasn't been observed live to confirm
  the exact wording `_OUT_OF_STOCK_RE` looks for.

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
   list. **Done. 576 survivors from 4178 Zatu products × 140,261 BGG base games — see the Stage 2
   section above for the breakdown.**
3. BGG enrich (best-effort, decoupled — don't block the pipeline if the token isn't ready yet).
   **Still blocked on the token — skipped ahead to Stage 5 instead of waiting (see below); start
   with the public-game-page HTML fallback (spec §0.1/§3 Stage 3) whenever it's picked back up.**
4. Philibert adapter (EAN first, title fallback). **Built and run for real — see the Stage 5
   section below. 174-game shortlist in `data/shortlist.json`** (after the matching-accuracy
   fixes documented there — was 201 before them).
5. Fill any Zatu detail gaps, then HTML render. **Done — v1 complete.** See the Stage 6/7 section
   below: `docs/index.html` is the live static report, 174 games, generated from real data.
   Composite score = advantage + quality + genre + language per spec §5, with two known gaps
   (documented in that section) rather than blockers: genre bonus scores 0 for everyone (the
   committed Zatu harvest predates the `is_coop`/`is_party` fields), and language is
   unconditionally `UNKNOWN` (Stage 3/BGG enrich is still blocked on the token).

**Noted for later, not blocking v1**: localisation — this tool and its output are currently
English/GBP-only (Zatu's UI, our column labels, French text only appears as raw Philibert data
inline). Not a v1 concern for a one-off personal trip-planning tool, but worth a deliberate look
once the pipeline itself is done, rather than backfilling it into every stage after the fact.

## Stage 5 — Philibert lookup + advantage filter (done, run against the real data)

`sources/philibert.py` (search + product-page parsing), `advantage.py` (spec §5.2's verdict
table), `scripts/enrich_zatu_ean.py` (Stage 4: real per-product EANs), `scripts/lookup_philibert.py`
(Stage 5 driver). All the *offline* logic (parsing, fuzzy title filtering, verdict computation) is
unit-tested against fixtures built from the real captured HTML (28 tests). The live run happened
via GitHub Actions (`.github/workflows/lookup-philibert.yml`) on 2026-08-10 — ~51 minutes for all
576 survivors (Stage 4 EAN enrichment: ~11 min; Stage 5 lookup: ~40 min).

- **Getting the search endpoint right took 7 probe rounds** (`scripts/probe_philibert.py`,
  2026-08-10) — see the Philibert bullet under "Data sources & gotchas" above for the full
  findings. Short version: wrong domain (round 1), guessed search URLs that all silently
  redirected to the homepage (rounds 1-2, 4), a JS-driven header search with no discoverable
  `<form>` (round 3), a bulk category-browse dead end at 12,812 products with broken pagination
  (round 5), and finally the real endpoint confirmed by a user-supplied working browser URL
  (rounds 6-7): `/fr/recherche?search_query=<query>`.
- **Real result (first run, since superseded — see the matching-fix bullets below)**: 565/576
  survivors got a real per-product EAN from Stage 4 (11 didn't — Zatu detail-page fetch failed or
  had no barcode). Of the 576 looked up on Philibert: 381 `LISTED_IN_STOCK`, 195 `NOT_LISTED`, 0
  `LISTED_OUT_OF_STOCK`. Advantage verdicts: 375 `NONE` (the actual ask — removed from the
  shortlist as "available in France at a similar price"), 195 `UNAVAILABLE_FR`, 6 `CHEAPER_UK`.
  Confirmed via a driver-level test that a same-price game is actually dropped from the shortlist
  while a genuinely-cheaper one and a not-listed-in-France one both survive.
- **Current real result, after the article-normalization + prefix-match + accessory-SKU-filter
  fixes below (`lookup-philibert.yml` re-dispatched 2026-08-10 16:39 — 53 min)**: 410
  `LISTED_IN_STOCK`, 166 `NOT_LISTED`, 0 `LISTED_OUT_OF_STOCK`. Advantage verdicts: 402 `NONE`,
  166 `UNAVAILABLE_FR`, 8 `CHEAPER_UK`. Outputs: `data/philibert_results.json` (all 576, verdict
  included, for transparency) and `data/shortlist.json` (**174** survivors — `NONE`/`EXCLUDED`
  removed, down from 201 before the fixes). The 27-game net drop in shortlist size is exactly the
  expected effect of the fixes: games that were wrongly falling through to `UNAVAILABLE_FR` due
  to the matching bugs are now correctly recognized as available in France (mostly landing in
  `NONE`, a couple in `CHEAPER_UK`) and correctly dropped from/reclassified in the shortlist.
  Slay the Spire itself is confirmed fixed: `LISTED_IN_STOCK`, real Philibert URL, €109.90,
  verdict `NONE` ("in stock both sides, UK only 2% cheaper below 40% threshold") — matching the
  user's real-world report exactly.
- **The zero-out-of-stock result was checked, not just accepted**: ran a follow-up probe against
  5 real product URLs from the actual run and confirmed `.product-actions` (the container
  `_classify_stock` uses) reliably contains the primary product's genuine "Ajouter au panier"
  text on all 5 — the selector guess was correct, and all 5 spot-checked products really are in
  stock. Still hasn't seen a real out-of-stock primary product live, so the exact wording is
  unconfirmed, but the container-scoping risk (the thing that actually mattered for correctness)
  checked out.
- **Can't yet distinguish `UNAVAILABLE_FR` from the weaker `UNAVAILABLE_FR?`** (spec §5.2) — that
  needs Stage 3's BGG "does a French edition exist" data, not built yet (blocked on the BGG
  token). Until then, every `NOT_LISTED` result uses the weaker variant (28 pts, flagged
  `needs_eyeball`) rather than assuming no French edition exists at all — the conservative
  default, revisit once Stage 3 lands.
- **Real false negative found by user spot-check, fixed 2026-08-10**: Slay the Spire was marked
  `UNAVAILABLE_FR` in the first real run even though Philibert lists it (under its French
  subtitle, "Slay the Spire: Le Jeu de Plateau"). Root cause was two-layered: (1)
  `normalize_title`'s article-stripping was leading-only (`^(a|an|the)\s+`) — stripping the noise
  phrase "board game" out of "Slay the Spire: **The** Board Game" left a dangling, ungrammatical
  "the" behind (`"slay the spire the"`) that a leading-only strip could never reach. Fixed by
  making `_ARTICLE_RE` match `\b(a|an|the)\b` anywhere in the string, substituting a space (not
  empty) to avoid gluing neighbouring words together. (2) Even with that fixed, `"slay spire"`
  only scores ~52-61 via `token_sort_ratio` against `"slay spire le jeu de plateau"` — nowhere
  near the 85 fuzzy threshold, since French-subtitled listings add unrelated tokens rather than
  extending the same words. Fixed by giving `search_by_title` the same unique-prefix fallback
  tier Stage 2's `BggIndex` already had (`sources/philibert.py`): tried only when fuzzy finds
  nothing, accepted only if exactly one candidate's normalized slug extends the query as a
  word-boundary prefix. Both fixes are unit-tested (`tests/test_match.py`'s new
  `"Slay the Spire: The Board Game"` case, `tests/test_philibert.py`'s
  `test_search_by_title_falls_back_to_unique_prefix_match` +
  `test_search_by_title_rejects_ambiguous_prefix_match`) — 119 tests pass initially, but **the
  real re-run still showed Slay the Spire as `NOT_LISTED`** (`lookup-philibert.yml` re-dispatched
  2026-08-10 16:29 — 55 min). Root-caused via `scripts/probe_philibert.py` against the live site:
  Philibert's own search was never the problem — all three query variants ("Slay the Spire: The
  Board Game", "Slay the Spire", "slay spire") returned the correct listing as the top hit. The
  bug was in our own prefix tier: Philibert also lists 4 accessory SKUs for the same game (a
  spare player board, a compatible upgrade-token set, a player board with lid, an expansion's
  component set) that ALL normalize to "slay spire ..." too, so the unique-prefix check saw 5
  candidates instead of 1 and correctly refused to guess. Fixed by filtering out links whose URL
  category slug is a known generic accessory-taxonomy term (`pions`,
  `pions-pour-jeux-specifiques`, `plateau-de-jeu-individuel`) before either the fuzzy or prefix
  tier runs — in every real sample seen so far (this game and all prior ones: Wingspan, Pandemic,
  Azul, Ticket to Ride, Spirit Island, Flip 7, Athletes de Compete) the *primary* board-game
  listing's category slug is always a publisher name, never one of these component-taxonomy
  slugs, so the filter can only help, never wrongly reject a real game. Verified against the real
  captured search results (`tests/fixtures/philibert_search_title_prefix.html`, rebuilt from the
  actual live probe output) — 119 tests still pass. **Confirmed fixed in the real re-run**
  (2026-08-10 16:39, see the updated Stage 5 result numbers above): Slay the Spire now resolves
  to `LISTED_IN_STOCK` at its real Philibert URL/price, verdict `NONE`.
- **Blood on the Clocktower, checked and not a bug**: user-supplied example where Zatu's EAN
  matches the *English* Philibert listing (confirmed "not available" — no French edition), while
  our title-search fallback would find the separate *French*-edition listing (different EAN, on
  preorder, `Langue(s)` = Français) instead. Traced by hand: EAN search on Zatu's own EAN
  correctly returns nothing (matches the user's cited English-listing URL, confirmed not
  purchasable there), so the pipeline's EAN tier behaves correctly. Whether the title-fallback
  then surfacing the French edition as `CHEAPER_UK`/`NONE` (rather than `UNAVAILABLE_FR`) is
  desired is a genuine judgement call, not a defect — user's framing ("for simplicity sake we can
  consider this as available") suggests accepting it, but this hasn't been explicitly confirmed
  either way and no code change was made for it.

## Stage 6/7 — composite scoring + static HTML report (done, v1 complete)

`score.py` (extended with `genre_points`/`language_points`/`composite_score`, spec §5.3-5.4),
`scripts/score_games.py` (Stage 6 driver: `data/shortlist.json` → `data/scored_games.json`,
sorted by composite score descending), `render.py` + `templates/report.html.jinja2` (Stage 7),
`scripts/render_html.py` (driver: `data/scored_games.json` → `docs/index.html`). Both stages are
pure offline computation over already-fetched JSON — no network calls, so unlike Stages 0/3/4/5
they were built *and run* directly in this coding sandbox, verified live with Playwright
(sort-by-column, filter-by-title, and the CHEAPER_UK/UNAVAILABLE_FR row rendering all confirmed
working against the real 174-game shortlist before committing) rather than needing a GitHub
Actions round-trip. 16 new tests (`tests/test_score.py`'s genre/language/composite cases,
`tests/test_score_games_script.py`, `tests/test_render.py`, `tests/test_render_html_script.py`) —
143 total passing.

- **Self-contained by design, deviating from spec §7's DataTables/Alpine suggestion**: the sort
  (click a column header) and filter (title search box) are both plain inline vanilla JS with no
  CDN dependency, since spec §6 itself calls for "a single self-contained file" and a CDN script
  tag would make the page depend on internet access to render correctly even though it's a static
  file. `tests/test_render.py` asserts no `<script src=...>`/`<link href=...>` at all, and that
  every in-page link only ever points at zatu.com/boardgamegeek.com/philibertnet.com.
- **Wired into `.github/workflows/lookup-philibert.yml`** as two more steps after Stage 5, so a
  live Philibert re-run always regenerates and commits `data/scored_games.json` +
  `docs/index.html` together with the shortlist — never lets the rendered report drift out of
  sync with the data it's supposed to reflect.
- **`docs/index.html` is GitHub Pages-ready** (a repo's `/docs` folder on the default branch
  needs zero extra config to serve) but Pages itself hasn't been enabled on the repo — that's a
  one-time manual step in the repo's Settings → Pages, not something this session can do.
- **Two known, documented gaps, not blockers** (both flagged inline in the rendered page too):
  - **Genre bonus scores 0 for every game right now.** `genre_points()` reads
    `zatu_is_coop`/`zatu_is_party`, but the *committed* `data/zatu_products.json` harvest predates
    `ZatuProduct.to_dict()` gaining those fields (confirmed: `is_coop`/`is_party` keys are
    entirely absent from the committed file, not just false) — every record's value is `None`,
    which `genre_points()` correctly treats as "no bonus" rather than a penalty, so this degrades
    gracefully rather than mis-scoring anything. Fix path when it's worth the ~50min GitHub
    Actions round-trip: re-run `harvest-zatu.yml`, re-run `scripts/match_bgg.py` (offline, safe
    here, ~2m15s) to regenerate `matched_games.json` with the fields populated, then re-run
    `lookup-philibert.yml` (now also re-runs Stage 6/7 automatically, see above).
  - **Language dependence is unconditionally `UNKNOWN` (-3 pts, `UNKNOWN_LANG` flag on every
    row)** — same root cause as Stage 5's `UNAVAILABLE_FR`/`UNAVAILABLE_FR?` gap: Stage 3 (BGG
    enrich) is still blocked on the BGG token. `language_points()` is written generically against
    a `"LOW"`/`"MED"`/`"HIGH"`/`None` level so it's ready to pick up real values the moment Stage
    3 lands, no signature change needed.
- **Not built**: the `results.csv`/`dropped.csv`/`run_metadata.json` sidecar files spec §6
  mentions (`dropped.csv` already exists from Stage 2, independently). `docs/index.html`'s own
  header line (generated timestamp, FX rate, discount threshold, harvest/survivor counts) covers
  the `run_metadata.json` content inline instead; a separate `results.csv` export would be
  redundant with `data/scored_games.json`, which already has everything in the same shape. Low
  priority for a one-off personal tool — worth adding only if CSV import into something else
  becomes an actual need.
- **PREORDER/VARIANT_EDITION flags aren't detected** (spec §6's flag badge list) — no upstream
  stage currently captures a preorder-wording signal or a deluxe/Kickstarter-vs-retail SKU
  signal, so there's nothing for `build_flags()` to read yet. `NEEDS_EYEBALL` and `UNKNOWN_LANG`
  (spec's other two) are both live.

## Post-v1 fixes from real user spot-checks (2026-08-10)

- **Genre bonus was 0 for every game — real bug, not just missing data.** The v1 gap note above
  ("committed harvest predates `is_coop`/`is_party`") was actually a red herring: `tags` was
  always present in `data/zatu_products.json` (confirmed live), but `scripts/match_bgg.py` read
  `product.get("is_coop")`/`.get("is_party")` — keys that only exist on a `ZatuProduct.to_dict()`
  object, never on the plainer dicts the committed JSON actually stores. Fixed by deriving both
  from `product["tags"]` directly via two new shared helpers (`sources/zatu.py`'s
  `is_coop_tag`/`is_party_tag`, also used by `ZatuProduct`'s own properties now, so the logic
  lives in one place). Purely offline — no re-harvest needed, `tags` was already there.
- **Re-running `match_bgg.py` after this fix also surfaced a second, unrelated staleness bug**:
  `match.py`'s dangling-article fix (commit `67622bd`, made for Stage 5's Slay the Spire miss)
  changed `normalize_title`'s output for every title with a mid-string article, but Stage 2's own
  `data/matched_games.json` was never re-run after that commit landed — it was silently stale
  relative to the code. Re-running it offline (safe, no network) gave **582 survivors** (574
  common + 8 newly matched, mostly `EXIT:` puzzle titles that couldn't match before + `This War
  of Mine` + 2 correctly *dropped* as newly-ambiguous: `HeroQuest` and `War of the Ring: The Card
  Game` now collide on normalized title with other BGG entries once "the" strips mid-string too —
  a correct precision improvement, not a regression). Committed the fresh
  `data/matched_games.json`/`data/dropped.csv`. The 8 new survivors and the corrected coop/party
  values for all 582 need a live Stage 4 (EAN)/5 (Philibert) re-run to get real
  price/availability data — bundled into the same GitHub Actions dispatch as the fixes below
  rather than a separate live round-trip.
- **`zatu_tags` (the raw Zatu tag list) is now carried through Stage 2's survivor records too**
  (previously only the derived `is_coop`/`is_party` booleans were kept) — needed for the new
  category-filter UI below.
- **Philibert base-title/family fallback, for a real false-negative class user-confirmed live**:
  `search_by_title` correctly found nothing for Zatu SKUs like "Everdell Complete Collection",
  "Cthulhu: Death May Die - Fear of the Unknown", and "Gloomhaven 2nd Edition" — not a
  matching-precision bug, those exact editions/expansions genuinely aren't listed — but the
  *base/family* game is (plain "Everdell", "Cthulhu: Death May Die", "Gloomhaven"), and the user
  wants that generalized: if the family exists in France, don't flag the SKU as a UK-exclusive
  buy. Added `sources/philibert.py`'s `_base_title_candidates()` (strips a " - "-separated
  expansion suffix, then edition/collection marketing noise, then falls back to the part before
  the first colon — most-specific tier first) and `search_family_title()`, tried only after the
  exact title search already found nothing, reusing `search_by_title`'s own fuzzy/prefix/
  accessory-filtering so a family hit still has to clear the same bar. Wired into
  `scripts/lookup_philibert.py`'s `lookup_one()` as a third tier after EAN and exact-title
  search. New `philibert_status` value `FAMILY_LISTED_FR` deliberately never compares this SKU's
  price against the family listing's price (different products) — `advantage.py`'s new
  `FAMILY_AVAILABLE_FR` verdict scores 0 points, flags `needs_eyeball`, and is excluded from the
  shortlist the same way `NONE`/`EXCLUDED` are (no genuine UK-buy urgency once the family is
  confirmed available in France). Unit-tested against synthetic fixtures (real captured HTML
  wasn't available for these specific title variants in this sandbox) — needs the same live
  GitHub Actions dispatch as above to confirm against the real 166 `NOT_LISTED` survivors,
  including the three real cases the user reported.
- **Category filter UI added to the HTML report**, per user request ("would love to filter on
  categories such as coop or party but even other from Zatu"). Coop/party get dedicated pinned
  checkboxes (reusing the now-fixed `zatu_is_coop`/`zatu_is_party`); `render.py`'s
  `clean_category_tags()` strips Zatu's player-count/duration/holiday/site-admin noise tags from
  the raw `zatu_tags` list (kept simple — a blocklist + a couple of regexes, not a full taxonomy)
  and `top_category_tags()` surfaces the ~24 most common surviving tags across the shortlist as
  additional checkbox chips (collapsed behind a "show more tags" toggle to keep the UI from being
  overwhelming). All still inline vanilla JS, no CDN dependency, consistent with the rest of
  Stage 7 — checking multiple boxes is OR (any selected category), combined via AND with the
  existing title-text filter. Verified live with Playwright against a synthetic multi-game
  fixture (coop-only, party-only, tag-only, and combined coop+tag+text filtering all behave as
  designed) since the real `docs/index.html` won't have real tag data until the live re-run
  above lands.
