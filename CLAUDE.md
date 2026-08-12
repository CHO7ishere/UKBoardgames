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

## "Not interested" hiding, persisted (2026-08-11)

User's follow-up: *"Would there be a way to save info entered in the website? Ideally in GitHub
if not in cookie but that would survive website rebuild. Typically I would like the ability to
be able to manually mark games as not interested and have them filtered out by default."*

- **Why not a live GitHub write from the browser**: the only way a static page (no backend) can
  write to the repo directly is by embedding a credential (a PAT) in client-side JS — but
  `docs/index.html` is served publicly by GitHub Pages, so any such token would be extractable by
  anyone who opens the page's source. Ruled out as a real security hole, not just inconvenient.
  Chose a two-tier design instead that needs no credential at all:
  1. **localStorage, per browser, zero-friction, immediate** — this alone already satisfies "survive
     website rebuild": localStorage lives outside the generated HTML entirely, so regenerating/
     redeploying `docs/index.html` (e.g. the next `lookup-philibert.yml` dispatch) never touches it.
  2. **`data/excluded_games.json`** (new, committed, empty `{"excluded_handles": []}` to start) —
     a plain-JSON-everywhere file in the same spirit as `data/bgg_fr_editions.json`: manually
     maintained, never auto-regenerated by any pipeline stage, read once by `render.py`/
     `scripts/render_html.py` and baked into every row as `data-user_excluded`. This is the actual
     "in GitHub" persistence: permanent, visible to every visitor/device, survives a browser's
     storage being cleared. Populated via the report's own "Export hidden list" button (downloads
     a file in the exact same shape) — copy it in as `data/excluded_games.json` and commit.
- **`render.py`**: `prepare_games()`/`render_html()` gained an `excluded_handles: set[str]`
  parameter, matched against `game["zatu_handle"]` (already the stable per-product identifier used
  throughout the pipeline) to set a `user_excluded` bool per game.
- **`scripts/render_html.py`**: new `load_excluded_handles()` + `--excluded` flag (default
  `data/excluded_games.json`), same "load if present, else empty" pattern as every other optional
  data file this script reads (`--unmatched`).
- **`templates/report.html.jinja2`**: each scored row gets `data-handle`/`data-user_excluded` +
  a "Not interested" button; controls row gets a "Show hidden (N)" checkbox, "Export hidden list",
  and "Clear hidden" button, plus a one-line explanation of the persistence model. JS: hidden state
  is a `Set` of handles, seeded once from the server-baked `data-user_excluded` rows on a browser's
  very first visit (so a fresh browser starts in sync with the committed list) and thereafter
  entirely localStorage-driven — so un-hiding a server-baked-excluded game on one device (e.g. "I
  changed my mind about this one") works locally without needing a code change. Hidden rows are
  excluded from the visible count/table by default; the "Show hidden" toggle reveals them dimmed
  (`.is-hidden`), still individually un-hideable. Kept scope to the main scored table only — the
  unmatched-games table doesn't get this (no meaningful "not interested" concept for games that
  were never even scored). Only applies to the *scored shortlist* table, not the unmatched list.
- **Real bug caught by live Playwright testing, not just unit tests**: `Array.prototype.slice.call(set)`
  silently returns `[]` for a `Set` (unlike a `NodeList`, a `Set` has no `.length`/indexed access,
  so it isn't array-like) — both `saveHiddenSet()` and the export handler used this pattern
  initially, so hiding *looked* like it worked (in-page state updated correctly) but silently wrote
  an empty array to localStorage and to the exported file every time. Would never have been caught
  by a DOM-only check (row hides/unhides fine in the same page load) — only surfaced by actually
  reloading the page and checking `localStorage.getItem(...)` inline via Playwright, per this
  project's own "test in browser before reporting complete" rule. Fixed by switching both to
  `Array.from(set)`. Verified end-to-end against the real 69-game report served over a local HTTP
  server (not `file://` — confirmed separately that Chromium doesn't reliably persist localStorage
  across reloads for `file://` origins, which would have been a false negative either way; the real
  GitHub Pages site is served over `https://`, a normal origin): hide persists across a reload,
  export downloads the correct `{"excluded_handles": [...]}` file, show-hidden reveals a dimmed row
  that can be un-hidden individually, clear-hidden resets to the original count. 227 tests pass (5
  new: `prepare_games` excluded-handle marking x2, a baked-`data-handle`/hide-button assertion on
  the self-contained-page test, `load_excluded_handles` x2, plus a `--excluded`-flag script test).

## Mobile layout (2026-08-11)

User: *"Can you optimize the display for mobile phone (iPhone 16 if that helps)?"* Verified before
and after with Playwright's built-in `iPhone 16` device profile (393×852 CSS px), not just by
eyeballing the CSS — the pre-existing page technically "worked" on mobile (viewport meta tag was
already there, `.table-wrap { overflow-x: auto }` meant no page-level horizontal scroll) but the
real problem was invisible from a desktop-only check: the 10-column table's `min-width: 1100px`
meant only Score/Game/Advantage were ever on-screen by default — Quality, price, Match, Flags,
and critically the row's own links *and* its new "Not interested" button were all off-screen,
reachable only by scrolling the table horizontally in isolation from the row's title.

- **Table → stacked cards below a 700px breakpoint**, `templates/report.html.jinja2`: `thead`
  hidden, each `tr` becomes a bordered card (`display: block`), each `td` a labeled line via
  `content: attr(data-label)` in `::before` — added a `data-label` attribute to every `<td>` that
  needs one (Score, Advantage, Quality, UK price, FR price, Discount, Match, Flags; the game
  title and the links row don't need a label, they're visually self-evident). The composite
  score is pulled out via `position: absolute` into a corner badge on the card rather than yet
  another labeled line, since it's the thing a user scans first. No Jinja reordering needed —
  the DOM order is unchanged, only mobile CSS display roles differ, so the desktop table markup/
  behavior is provably untouched (confirmed via a 1400px-viewport Playwright check after the
  change: `thead` still visible, table still a real `<table>`).
- **Sort-by `<select>`, CSS-hidden above 700px**: clicking a column header to sort doesn't exist
  once `thead` is hidden, so a dropdown (`#games-sort-select` / `#unmatched-sort-select`)
  encodes `key|type|dir` per option and reuses the exact same `sortRows()`/header-highlighting
  logic as desktop (refactored the shared bit into `applySortAndMarkHeader()` so there's one
  code path, not two). Each table's dropdown only lists its own genuinely useful columns (not
  all 10) — full column-by-column sorting isn't essential on a phone, a handful of the ones
  someone would actually reach for while standing in a shop is enough. Default option matches
  each table's existing default sort exactly, so switching to mobile width never silently
  reorders anything.
- **Fixed a real pre-existing gap found while doing this, not a new regression**: `#unmatched-filter`
  (the second table's title-search box) had no CSS at all — only `#filter` (the main table's) was
  ever styled, so it rendered as an unstyled native input on every screen size, not just mobile.
  Both now share a `.filter-input` class.
- **iOS zoom-on-focus avoided**: both filter inputs' font-size was `0.95rem` (~15.2px); Safari on
  iOS auto-zooms the page on focusing any input under 16px. Bumped to `1rem` globally (not just
  in the mobile media query — no reason for it to differ by breakpoint).
- **Touch targets sized up for the elements people actually tap repeatedly on a phone**: the
  "Not interested" button measured 92.7×20.8px pre-fix (well under Apple's 44pt HIG guidance) —
  confirmed via a live Playwright `bounding_box()` read against the real rendered page, not a
  visual guess. Bumped its mobile padding/font-size to ~115×33px, plus a similar bump for the
  category filter chips and the export/clear buttons. The native checkbox for "Show hidden" stays
  small (13×13px) by design — it's wrapped in a `<label>` whose full text is also clickable
  (confirmed its real hit area is 154×31px), so the visible checkbox size doesn't reflect the
  actual tap target.
- **Verified live end-to-end on the real 69-game report**, not just unit tests: at the iPhone 16
  viewport — no page-level horizontal scroll (`scrollWidth === clientWidth === 393`), cards render
  with all fields reachable without scrolling, the sort dropdown re-orders rows exactly like the
  desktop header click would, the title filter and coop/party category chips both still work, and
  the "Not interested" flow (tap to hide, `localStorage` persists across a reload, "Show hidden"
  reveals it dimmed, export downloads the right JSON) all still work unchanged on the new layout.
  Re-checked the desktop view at 1400px afterward to confirm zero visual/behavioral difference
  there. 227 tests pass (2 new: `data-label`/`games-sort-select` presence asserted on the
  self-contained-page test, guarding the mobile card layout against a silent regression).

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

**Live re-run results (`lookup-philibert.yml` dispatched 2026-08-10 18:34, ~62 min, commit
`766f419`)**, confirming all four fixes above against the real 582-survivor set: 409
`LISTED_IN_STOCK`, 142 `NOT_LISTED`, 31 `FAMILY_LISTED_FR` (the new tier). Verdicts: 401 `NONE`,
142 `UNAVAILABLE_FR`, 31 `FAMILY_AVAILABLE_FR`, 8 `CHEAPER_UK`. Shortlist: **150** games (down
from 174 — expected: family-available games no longer inflate it, plus the corrected
582-survivor base). Coop/party counts are real now: 32/8 (was 0/0). All three user-reported
cases confirmed fixed: Everdell Complete Collection and Everdell: Silverfrost Collector's
Edition both → `FAMILY_AVAILABLE_FR` (matched to plain "Everdell"); Cthulhu: Death May Die -
Fear of the Unknown → `FAMILY_AVAILABLE_FR` (matched to base "Cthulhu: Death May Die"). Category
filter UI verified live with Playwright against the real `docs/index.html`.

- **New precision bug found via this same live run, fixed 2026-08-10 (not yet re-verified live —
  see below)**: scanning the real results for accessory-looking URLs turned up 3/582 games
  (Gloomhaven: Jaws of the Lion, Orloj: The Prague Astronomical Clock, Minos: Dawn of the Bronze
  Age) matched to Philibert **accessory/insert listings** instead of the real game — e.g.
  Gloomhaven: Jaws of the Lion (a top-12 BGG-ranked, `EXCELLENT`-quality game) matched a €27.50
  third-party storage insert ("Insert: Gloomhaven Jaws of the Lion", listed under `poland-games`,
  an ordinary-looking publisher slug the existing `_is_accessory_link` category-slug check
  doesn't catch since it's not one of the generic component-taxonomy slugs). `token_sort_ratio`
  barely penalizes one extra token on an otherwise-identical title, so it cleared the fuzzy
  threshold — producing a bogus price comparison (UK "53% more expensive") and silently dropping
  a genuinely strong game into `NONE`/excluded-from-shortlist. Fixed with a second, distinct
  accessory signal in `sources/philibert.py`: `_has_accessory_token` drops any search candidate
  whose normalized title carries an accessory-indicator word (`insert`, `rangement`,
  `organiseur`/`organizer`/`organisateur`) that the query itself didn't ask for, regardless of
  slug/category — catches title-text accessories the URL-category-slug filter structurally can't
  see. Unit-tested against a fixture rebuilt from the real miss (confirmed the fix rejects it,
  and doesn't reject a real "Deluxe"-suffixed title with only unrelated extra words). Small
  blast radius (3/582 ≈ 0.5%) — per user's explicit choice, this was pushed as a code+test fix
  without spending another ~hour-long GitHub Actions round-trip just for these 3 games; the next
  live Philibert re-run (whenever one happens for other reasons) will pick it up.
- **Marvel Champions: The Card Game, another real miss (user-confirmed live)**: the exact-title
  and bare base-title ("Marvel Champions") searches both correctly found nothing/refused to
  guess — Marvel Champions has 15+ expansion/hero-pack SKUs on Philibert sharing that prefix.
  Publishers translate a literal "The X Game" suffix into French "Le Jeu de X" — confirmed as a
  real recurring pattern across two independently-found games now (Slay the Spire's "Board
  Game", this one's "Card Game"). Added `_translated_title_candidate()` to
  `sources/philibert.py`, tried first in `_base_title_candidates()`: the translated candidate
  ("Marvel Champions: Le Jeu de Cartes") is an exact normalized match for the real base box and
  wins the ordinary fuzzy tier outright (100.0 vs 89.19 for the closest real expansion, verified
  against real captured Philibert search data before shipping).
- **A second accessory false-positive class, found the same way as the insert bug above**: the
  accessory-token fix (`_has_accessory_token`) also silently fixed Orloj: The Prague Astronomical
  Clock and Minos: Dawn of the Bronze Age, which were matching accessory listings before.
- **Live re-run confirming both fixes** (`lookup-philibert.yml` re-dispatched 2026-08-11 05:08,
  ~58 min, commit `f23158d`) against the real 582-survivor set: Marvel Champions: The Card Game
  → `FAMILY_LISTED_FR`/`FAMILY_AVAILABLE_FR` at the real base-box URL; Gloomhaven: Jaws of the
  Lion and Minos: Dawn of the Bronze Age → correctly `NOT_LISTED` (no longer matched to
  accessories); Orloj → `FAMILY_LISTED_FR` at a real listing. Verdicts: 398 `NONE`, 142
  `UNAVAILABLE_FR`, 34 `FAMILY_AVAILABLE_FR`, 8 `CHEAPER_UK`.
- **Real process bug found and fixed the same day**: this exact live run *initially* failed
  silently — Stages 4-7 all completed for real, but the final `git push` was rejected
  (non-fast-forward) because several more code-only commits landed on `main` during the ~1hr
  run, discarding the entire run's output (it only existed in the ephemeral runner's local
  checkout). Fixed `lookup-philibert.yml`'s commit step to `git fetch` + `git rebase
  origin/main` before pushing, with a few retries — then re-dispatched, which is the run whose
  results are recorded above.
- **BGG's public game page is Cloudflare-protected** (confirmed live via
  `scripts/probe_bgg_page.py`): every plain `requests` call returns a 403 "Just a moment..."
  challenge page, main page and `/versions` alike — no header trick gets around it. A **real
  headless browser does**, though (confirmed via `scripts/probe_bgg_playwright.py`, Playwright +
  Chromium in GitHub Actions): loads the real page, no challenge, `Language Dependence` poll text
  present and extractable. The plain `/versions` page render looks nearly identical to the main
  page (real version data loads via a later client-side call our fixed wait didn't catch) — but
  BGG's versions page takes a `?language=<id>` filter (user-supplied lead), and that DOES change
  the *server* response: confirmed live against Spirit Island (`?language=2187` → 4 real French
  printings, `/boardgameversion/.../french-edition-{first,second,third,fourth}-printing`) and
  Marvel Champions (→ exactly 1 French edition, titled **"Marvel Champions: Le Jeu De Cartes"** —
  an exact match to the real Philibert listing, extracted directly from BGG with zero translation
  guessing). This is a real, generalizable Stage 3 foundation — solves both the `fr_edition_exists`
  gap (spec §5.2) and gives an authoritative localized title, better than the Wikidata partial-
  coverage approach (`scripts/probe_wikidata.py`: BGG-ID cross-reference via P2339 found a usable
  French label for only 2/5 test games — Gloomhaven and the original Sherlock Holmes Consulting
  Detective, no labels for Marvel Champions or Everdell). Not yet built into the pipeline — a
  headless-browser scrape is slow (~7-8s/page observed, ~582 games x ~1-2 requests would be a
  ~1-2hr run) and, per the user's explicit ask (2026-08-11), needs a real caching layer first so
  re-runs don't re-fetch already-known data from scratch every time.
- **Real caching added for Stage 4/5, prompted by a real wasted run**: `docs/spec.md`/this
  file's own "Tech" section always intended a cache ("SQLite cache keyed by source+id,
  incremental re-runs, resumable") but it was never actually built — confirmed by re-reading
  `scripts/enrich_zatu_ean.py`/`scripts/lookup_philibert.py`: both unconditionally re-fetched
  every survivor on every dispatch, even ones already resolved in a prior run's committed
  output. This session alone re-ran the full 582-game Philibert lookup twice (once lost entirely
  to the git-push race documented above) — real, wasted load on Philibert's servers and ~50-60
  min of GitHub Actions time each time, for data that mostly hadn't changed. Fixed by reusing the
  existing committed JSON files as the cache (no new SQLite/binary artifact, consistent with the
  project's existing plain-JSON-everywhere shape):
  - `enrich_zatu_ean.py` skips any survivor that already has a `zatu_ean` value (Zatu barcodes
    are static per-product data, essentially never change) — `--refresh` forces a full re-fetch
    when genuinely needed.
  - `lookup_philibert.py` loads its own `--out` file (`data/philibert_results.json`) from the
    *previous* run before overwriting it, and reuses any survivor whose cached
    `philibert_status` is durable (`LISTED_IN_STOCK`/`LISTED_OUT_OF_STOCK`/`FAMILY_LISTED_FR` —
    once genuinely found, a matching-precision fix can only ever find *more* real listings, never
    un-find a confirmed one). `NOT_LISTED` is deliberately **never** cached/trusted — that's
    exactly the state a matching fix is meant to change, so it's always re-checked live. The
    `advantage` verdict itself is always recomputed fresh from current survivor/config data even
    for cache hits (cheap, pure computation, no network) rather than trusted stale from the
    cache. `--refresh` bypasses the cache entirely.
  - Net effect: a re-run after a matching-precision fix now only pays live-network cost for the
    ~24% of survivors that were `NOT_LISTED` (exactly the ones a fix could plausibly change) plus
    any brand-new survivors, not all 582 every time.
  - GitHub Actions workflows need no changes — `lookup-philibert.yml` already runs Stage 4 then
    Stage 5 against the same committed files, so caching kicks in automatically on the next
    dispatch.

## Stage 3 built for real — BGG French-edition-exists via headless browser (2026-08-11)

Prompted by a real user-reported case: the site correctly started showing Gloomhaven: Jaws of
the Lion as `UNAVAILABLE_FR` after the accessory-insert fix (git blame: it's genuinely not on
Philibert), but the user pointed out BGG's own versions data
(`boardgamegeek.com/boardgame/291457/gloomhaven-jaws-of-the-lion/versions?pageid=1&language=2187`)
confirms a real French edition exists — just not currently purchasable anywhere. Stated intent:
*"I don't want to buy English versions if a French one exists (even if unavailable)"* — exactly
the `fr_edition_exists` gap `advantage.py` was always designed for (spec §5.2's `UNAVAILABLE_FR`
vs the weaker `UNAVAILABLE_FR?`) but never had real data behind, since Stage 3 was blocked on the
BGG API token.

- **`sources/bgg_versions.py`** (new): `fetch_french_edition_info(page, bgg_id)` takes a real
  Playwright `page` object (not `requests` — BGG blocks plain HTTP with a Cloudflare challenge,
  confirmed via `scripts/probe_bgg_page.py`; a real headless browser gets through untouched,
  confirmed via `scripts/probe_bgg_playwright.py`). Uses the `?language=<id>` filter on BGG's
  versions page (user-supplied lead) — confirmed live this changes the *server* response, not
  just client-side JS: Spirit Island → 4 real French printings, Marvel Champions → exactly 1
  French edition titled **"Marvel Champions: Le Jeu De Cartes"**, an exact match for the real
  Philibert listing extracted with zero translation guessing.
- **Needs the real BGG slug, not just the numeric id** — confirmed live a slug-less
  `/boardgame/<id>/versions?language=<id>` request gets silently redirected to the plain game
  page (dropping `/versions` and the query entirely, 0 results, not an error) rather than
  filling in the slug itself. Resolved with an extra page load: visit the bare `/boardgame/<id>`
  page first (BGG's own redirect fills in the canonical slug), read the final URL, then build
  the real versions URL from that — 2 navigations per game, not 1.
- **`scripts/enrich_bgg_fr_edition.py`** (new, Stage 3 driver): scoped to survivors that are
  either brand new or were `NOT_LISTED` on Philibert in the last run (per
  `data/philibert_results.json`) — `fr_edition_exists` is only ever read by
  `compute_advantage`'s `NOT_LISTED` branch, so checking games Philibert already found live
  would be wasted browser time. Writes `data/bgg_fr_editions.json` (keyed by `bgg_id`), reusing
  the same cache-by-committed-JSON pattern as Stage 4/5: once a `bgg_id` is checked, it's cached
  indefinitely (this is BGG's own catalogued version data, essentially static) — `--refresh`
  forces a full re-check.
- **Wired into `scripts/lookup_philibert.py`**: loads `data/bgg_fr_editions.json` and passes
  `fr_edition_exists` into `compute_advantage` by `bgg_id` — no changes needed to `advantage.py`
  itself, it was already written generically against this exact parameter.
- **`.github/workflows/lookup-philibert.yml`** renamed to reflect Stage 3+4+5, gained a
  `playwright install --with-deps chromium` step and a new "Stage 3" step before Stage 4,
  running before Stage 5 so the fresh `data/bgg_fr_editions.json` is available when advantage
  verdicts are computed. `requirements.txt` gained `playwright` (needed for `tests.yml`'s
  offline unit tests to even import the module, not just for the live browser run).
- **Cost**: scoped to ~142 `NOT_LISTED` survivors (not all 582) since that's the only branch
  that reads this data, but each one is 2 real browser page loads at ~13s apiece (navigation +
  a 6s settle wait, the same wait strategy already proven reliable — `networkidle` was tried and
  confirmed to hang, BGG never goes fully network-idle) — roughly another ~45-60 min added to
  the live pipeline run on top of Stage 4/5's existing runtime. Not yet re-dispatched against
  real data as of this note.
- **Live-dispatched for real (2026-08-11)**: 141 of the 142 `NOT_LISTED` survivors got a real
  BGG check (1 had no prior Philibert record to key off, left unchecked this round) — **91 of
  the 141 (~65%) have a real French edition somewhere per BGG**, only 50 confirmed to have none
  at all. Real example: Gloomhaven: Jaws of the Lion's French title is "Gloomhaven: Les Mâchoires
  du Lion".
- **User's follow-up made the design intent explicit and changed the verdict, not just the
  reason text**: the original plan (spec §5.2) was to keep `fr_edition_exists=True` inside
  `UNAVAILABLE_FR` as the *weaker* variant (fewer points, `needs_eyeball`) — still shown, still
  "buy in the UK" advice, just flagged as less certain. Real user pushback after seeing
  Gloomhaven still on the site: *"I don't want to buy English versions if a French one exists
  (even if unavailable)"* / *"everything that has a French version just needs to be removed."*
  That's a stronger ask than the spec's own framing — a known French edition (even a currently-
  unpurchasable one) means this is **not a genuine UK-exclusive buy at all**, not just a less-
  confident one. Added `VERDICT_FRENCH_EDITION_EXISTS` to `advantage.py`, excluded from the
  shortlist the same way `NONE`/`FAMILY_AVAILABLE_FR` are. `fr_edition_exists=None` (Stage 3
  hasn't checked this game) still gets the old weak/uncertain `UNAVAILABLE_FR` — "we don't know"
  is genuinely different from "we know and it exists."
- **Applied to the just-fetched live data entirely offline** — added `lookup_philibert.py
  --offline` (reuses every survivor's cached `philibert_status` as-is, including `NOT_LISTED`,
  which the default cache policy always re-checks live; only the advantage verdict itself is
  recomputed) specifically so an `advantage.py` logic change like this one doesn't need a second
  ~2hr live re-run just to take effect. Real result: 92 games now `FRENCH_EDITION_EXISTS`
  (excluded), shortlist dropped from **150 to 58**. All three Gloomhaven SKUs (`Jaws of the
  Lion`, `2nd Edition`, `Buttons & Bugs`) confirmed excluded — verified both in
  `data/philibert_results.json` and live in the rendered `docs/index.html` via Playwright (0
  results for a "gloomhaven" title-filter search).
- **On "cache" as a word**: user's own framing, worth keeping — BGG's French-edition-exists data
  is BGG's own static catalogue, not a fetch result that can go stale the way Philibert stock/
  price can. Calling `data/bgg_fr_editions.json` a "cache" undersells it; once written it's
  functionally permanent data, only ever added to (new bgg_ids) or explicitly corrected
  (`--refresh`), never expired on its own.

## Stage 2 matching improvements + unmatched-games list (2026-08-11)

User's follow-up after seeing the shortlist shrink to 58: *"I did not find anything amazing in
the current list. I wonder if in the games from Zatu we did not match in bgg there is not more
potential"* — asked for (1) a visible list of Zatu games Stage 2 never matched to BGG at all, so
they could eyeball it for hidden gems, and (2) a look at whether matching itself could be
improved for the near-miss cases. Both offline, no network needed.

- **Real normalization bugs found and fixed in `match.py`**, each backed by a concrete
  before/after from the real 3597-row `dropped.csv`, not a hypothetical:
  - **"Vol." abbreviation**: BGG spells out "Volume One"/"Volume Two", Zatu abbreviates
    "Vol. 1"/"Vol 2" — `_VOL_DOT_RE`/`_VOL_WORD_RE` expand the abbreviation to "volume" (kept,
    not stripped as noise — the volume number is exactly what distinguishes these entries).
  - **Word-numbers**: paired with the above, BGG spells "One"/"Two"/"Three" as words where Zatu
    uses digits — `_WORD_NUM_RE`/`_WORD_NUM_MAP` convert them the same way roman numerals
    already were, so both sides land on the same digit token.
  - **"The Game" as a franchise qualifier**: BGG catalogues the whole EXIT: puzzle-room series
    as "EXIT: The Game – <subtitle>", but Zatu drops "The Game" entirely
    ("EXIT: The Sinister Mansion") — added to `_EDITION_NOISE_RE` alongside the existing "board
    game"/"card game" phrases. Safe even in the worst case: if two genuinely different BGG
    entries only differ by "the game", stripping it just makes them collide into the
    ambiguous-exact-match branch (correctly dropped), never a wrong silent match.
  - **"v." as "versus", not roman numeral V**: found as a real *regression* the fixes above
    exposed — once "Season One" became "Season 1" on both sides, a preexisting latent bug (the
    roman-numeral regex misreading Dice Throne's "... Pyromancer v. Shadow Thief" abbreviation
    as roman "V" = 5) started a genuine digit ("1") disagreeing with a fake one ("5"), tripping
    the digit-conflict veto on a game that used to match by accident (previously masked because
    only one side ever carried a digit). Fixed by normalizing "v." (only when followed by
    whitespace, so a genuine roman "V" edition number is never touched) to "vs" before the
    roman-numeral pass ever sees it — confirmed via `bg_ranks.csv` that all 23 real "v."
    occurrences are this exact Dice Throne matchup-naming convention, nothing else.
  - **Real, measured result** (re-running `scripts/match_bgg.py` offline against the live 4178×
    140,261 corpus, verified via a before/after diff of `data/matched_games.json` survivor
    handles): 582 → **589 survivors, net +7, zero regressions** — 3 EXIT titles, 3 "Unmatched:
    Battle of Legends" volumes, 1 Dice Throne matchup recovered; nothing that used to match
    stopped matching. All 205 tests (36 in `test_match.py` alone) still pass unchanged.
- **`MatchResult` gained a `candidates` field** (`match.py`) — purely informational, populated
  only on LOW-confidence results (the single best fuzzy/digit-conflict candidate, or up to 5 tied
  exact/prefix candidates), never used to decide match/no-match. `bgg_id`/`bgg_name` stay `None`
  on LOW exactly as before, so nothing downstream can mistake this for an actual match — it
  exists solely so a human can see *why* something looked close without re-running the matcher.
- **New unmatched-games list**: `scripts/match_bgg.py`'s `run()` now returns a third list
  alongside survivors/dropped — every LOW-confidence-dropped product that isn't itself an
  accessory (reusing `filters.py`'s accessory check, refactored into
  `is_probably_accessory_fields()` so it works off plain dict fields, not just a `ZatuProduct`),
  carrying full Zatu fields (price, stock, tags, coop/party) plus a categorized `match_category`
  (`NO_CONFIDENT_MATCH`/`AMBIGUOUS_EXACT`/`AMBIGUOUS_PREFIX`/`DIGIT_CONFLICT`) and the candidate
  info above. Written to `data/unmatched_games.json` (real result: **2220 games** — 1911 no
  confident match, 283 ambiguous-exact, 21 ambiguous-prefix, 5 digit-conflict — after excluding
  accessories from the raw 2227 LOW-confidence drops). Deliberately distinct from spec P2's
  "ambiguous matches never surfaced for manual review" — that principle is about *auto-picking*
  one of several tied BGG candidates (still never done), not about hiding the raw dropped list
  itself from a human who explicitly asked to see it.
- **`docs/index.html` gained a second, collapsed-by-default `<details>` section** ("Not
  matched to BGG (2220 games)") below the main scored table — its own sortable/filterable table
  (`render.py`'s `prepare_unmatched()`/`build_closest_bgg_guess()`), reusing the same coop/party/
  tag category-filter chips. Default sort is by fuzzy match score descending (nulls/ambiguous
  cases sort last, real near-misses bubble to the top) so the most promising "did we just miss
  this" candidates are the first thing seen on expand — confirmed live via Playwright: "Battle
  Royale: Last One Standing" (100% similar, dropped only for being too close to a runner-up) and
  the remaining Dice Throne/EXIT near-misses surface first, exactly as intended. The main table's
  sort/filter JS was refactored into a shared `setupTable()` function called twice (was a single
  inline IIFE) rather than duplicating ~90 lines of JS for the second table. Still fully
  self-contained (no CDN, verified by the existing `test_render.py` domain-allowlist assertion,
  which now also covers the new `boardgamegeek.com` search-link URLs) — `docs/index.html` is now
  ~2.5MB (2220 extra rows), still loads and filters instantly in a live Playwright check.
- **Not yet live**: the 7 newly-recovered survivors (from the matching fixes above) are in the
  refreshed `data/matched_games.json` but don't have Stage 3/4/5 data (BGG French-edition check,
  EAN, Philibert lookup) yet — `data/shortlist.json`/`data/scored_games.json` and the main
  scored table in `docs/index.html` are unchanged from the last live run until the next
  `lookup-philibert.yml` dispatch picks them up (their Philibert-lookup cache only skips
  survivors it already has an entry for by `zatu_handle`, so these 7 will be fetched live, not
  skipped). The new unmatched-games list itself needed no live run at all — every field it uses
  (Zatu price/stock/tags, BGG candidate names) was already sitting in already-fetched local
  files.

## Excluded-expansion exact-match veto — a real wrong live match found and fixed (2026-08-11)

User's follow-up proposal: generalize matching further — treat words like "box"/"set"/
"edition"/"standalone" as noise, or more broadly, "if one title is fully included in the other,
say it's a match." Investigated by mining `data/unmatched_games.json`'s near-miss scores for
real "box"/"set"/"standalone" cases and checking each candidate's `is_expansion` flag in the
full (unfiltered) `bg_ranks.csv` — not implemented as proposed, because the evidence pointed the
other way: **a blanket containment rule would introduce new wrong matches, not just fix
misses**, and surfaced a real one already live.

- **The concrete counter-evidence**: BGG catalogues huge expansion families under the exact
  same words the proposal wanted treated as generic noise — `Terraforming Mars: Big Box` is
  itself a real, separate `is_expansion=1` entry (distinct from base `Terraforming Mars`), and
  `Nemesis`/`Summoner Wars`/`MicroMacro` each have 20-100+ real expansion/promo entries sharing
  their base title plus one extra word. Stripping "box"/"set"/"standalone"/"expansion" as
  generic noise, or accepting containment in the query-has-extra-words direction, would
  routinely match a specific (often much cheaper) expansion SKU to the wrong, much larger base
  game — a bogus price comparison, not just an imprecise one.
- **That exact failure mode turned out to already be live**, found by checking every current
  survivor's `bgg_id` against `bg_ranks.csv`'s full (unfiltered) expansion list: **`Terraforming
  Mars - Ares Expedition: Crisis`** (Zatu's real handle, a £17 mini-expansion) was matched to
  base game **`Terraforming Mars: Ares Expedition`** at 90.4% fuzzy — comparing the wrong two
  products' prices. The real BGG entry for it (`Terraforming Mars: Ares Expedition – Crisis`,
  id 358738, `is_expansion=1`) exists and normalizes to an *exact* match of the query; it's
  excluded from the match corpus only because it's an expansion (`include_expansions: false`
  in config.yaml, spec's own "you're buying playable boxes" rule), not because it's unknown.
  Confirmed this hadn't yet reached the *published* report (checked `data/shortlist.json`/
  `data/scored_games.json` — this handle wasn't in either), but it was sitting in
  `data/matched_games.json` ready to be picked up by the next live Philibert dispatch.
- **The fix** (`match.py`'s `BggIndex`): a new optional `excluded_games` parameter builds a
  second exact-title index over whatever `filter_base_games` dropped (real BGG expansions).
  Before falling through to fuzzy/prefix matching, `.match()` now checks this index first — if
  the query's normalized title *exactly* matches a specific excluded entry, it refuses to match
  the base game and returns LOW confidence instead, carrying that excluded entry as a
  `candidates` entry for transparency. This is a precision-only change: it only fires on an
  *exact* normalized-title hit against a real, specific, known BGG entry — never a guess, and
  strictly narrower than a fuzzy/containment rule. `scripts/match_bgg.py` computes
  `excluded_games` as `all_bgg_games - bgg_games` (by id, not a costly list `in` check) and
  threads it through; a new `MATCHES_EXCLUDED_EXPANSION` category surfaces these in the
  unmatched-games list distinctly from genuine no-BGG-match products.
- **Real, measured result**: re-running `scripts/match_bgg.py` against the live corpus:
  589 → **586 survivors, -3**, all three confirmed real catches by checking their excluded
  candidate's `is_expansion` status — `Terraforming Mars - Ares Expedition: Crisis` (the bug
  above), `Tokyo Highway: Rainbow City - Solo` (matched to base `Tokyo Highway: Rainbow City`,
  real excluded entry is `Tokyo Highway: Rainbow City – SOLO`, id 418305, a distinct solo-mode
  expansion), and one genuinely mixed case: `Bios: Origins 2nd Edition` used to correctly
  fuzzy-match `Bios: Origins (Second Edition)` at 95% (a real base-game entry) — but its
  normalized query also happens to *exactly* equal `BIOS: Origins` (id 134068), BGG's *first*
  edition, which BGG's own data oddly flags `is_expansion=1` (relative to the second edition,
  not a physical add-on) — so the veto fires here too and this one is arguably a recall loss,
  not a pure win. Kept as-is deliberately: per the project's own precision-over-recall design
  (spec P2), dropping a good-but-uncertain match is the correct failure direction for a tool
  that recommends real purchases — and this exact case is exactly what the unmatched-games list
  exists for: it's visible there with `BIOS: Origins` shown as the reason, so a human can
  eyeball it and know it's actually fine, rather than trusting a silent wrong price comparison
  elsewhere. All 209 tests pass (`tests/test_match.py`'s new veto tests reproduce the real
  Terraforming Mars bug directly — one test with `excluded_games` omitted confirms the bug
  reproduces, one with it passed confirms the fix; `tests/test_match_bgg_script.py`'s new test
  uses `bg_ranks_sample.csv`'s existing real `Spirit Island: Branch & Claw` expansion fixture
  end-to-end).
- **On the original proposal**: not implemented as a blanket rule, but the underlying idea (find
  more matches by tolerating small title differences) is exactly what the earlier Vol./"the
  game"/word-number fixes in this same session already did — the difference is that those were
  each verified safe against the real corpus first (checked they don't collide with any other
  real entry), the same bar this veto fix now also enforces automatically for the specific
  "extra content word names a real different product" risk class.

## Philosophy check-in + light-tier exact match (2026-08-11)

User's follow-up: *"We need to change the philosophy. Purpose is to find games and the list
right now is very limited."* Also confirmed two things already in place are correct, not new
asks: (1) any French availability at all (translated edition, or even just an English listing on
Philibert) means "don't buy in the UK" — matches the existing `NONE`/`FAMILY_AVAILABLE_FR`/
`FRENCH_EDITION_EXISTS` exclusions exactly; (2) an expansion-vs-base price comparison being
"skewed" should be handled by *dropping* the comparison, not fixing it — exactly what the
excluded-games veto above already does.

- **Asked via `AskUserQuestion`** whether to loosen the two most obvious levers, with real
  numbers attached: the discount threshold (40% -- only 8/398 "available but not cheaper enough"
  games would flip to `CHEAPER_UK` at 25%, more at 15%/uncapped) and the BGG quality gate (7.2
  shrunk score -- 205/404/852 more games would enter the pool at 7.0/6.8/6.5). **User kept both
  at their current values** — neither was the actual bottleneck.
- **Follow-up question narrowed it to the real cause**: user picked *"Matching coverage itself
  is the bottleneck"* — only 586 of 4178 Zatu products were reaching a confident BGG match at
  all before this session's fixes, out of proportion to the catalogue's real size.
- **Root cause found by mining the 283-strong `AMBIGUOUS_EXACT` bucket**: `normalize_title`'s
  own edition-noise stripping ("Big Box", "Card Game", "Deluxe Edition", etc.) is applied to
  *both* the query and BGG's own catalogued names before the exact-match check — so real,
  separately-priced BGG products like "Carcassonne" (id 822) and "Carcassonne Big Box" (id
  142057) collide onto the identical stripped string "carcassonne" and become falsely
  ambiguous, even though the query text itself (e.g. Zatu literally titling a product
  "Carcassonne Big Box") still said exactly which one it meant. A simulation against the real
  283-entry bucket confirmed 106 entries are only ambiguous for this reason (vs. 177 genuinely
  identical BGG names with no textual signal to disambiguate, left alone) and that 68 of those
  106 would cleanly resolve if the query's own un-stripped text were checked first.
- **Fix**: `match.py` gained `normalize_title_light()` — identical to `normalize_title()` except
  it does *not* run `_EDITION_NOISE_RE` (keeps every other step: accents, HTML entities,
  vol./word-number/roman-numeral spelling alignment, punctuation, articles — none of those lose
  real product-identity information). `BggIndex` now tries an exact match against this lighter
  normalization *first*; only when it uniquely resolves to one candidate does it short-circuit
  to a HIGH match, since anything the light tier finds ambiguous can only stay ambiguous (or
  grow more so) once the aggressive tier's stripping merges further groups together — so falling
  through to the existing pipeline in that case is still correct and produces a more complete
  candidate list for the unmatched-games display. This is a strict precision improvement, not a
  recall-for-precision tradeoff: it only ever *adds* a specific, correct identification (the
  query's own words already said which product it meant), never introduces a new wrong guess.
- **Real, measured result** (re-running `scripts/match_bgg.py` offline against the live corpus):
  586 → **621 survivors, net +35, zero regressions** — confirmed via a before/after diff of
  every survivor handle; nothing that used to match stopped matching. Real recoveries include
  both directions of the same fix working correctly on the same query family: `Carcassonne` →
  base game (id 822) *and* `Carcassonne Big Box` → the Big Box entry (id 142057) as two distinct,
  now-correct matches, plus `Colt Express: Big Box`, `Istanbul Big Box`, `K2: Big Box`, `Oh My
  Goods! Big Box`, `Port Royal Big Box`, `Nusfjord Big Box`, `Carson City Big Box`, `Dominion
  (Second Edition) Big Box`, `Cat in the Box: Deluxe Edition`, and several more. `HeroQuest` and
  `War of the Ring: The Card Game` — both flagged as new regressions in the earlier
  dangling-article-fix commit — are recovered too, now correctly disambiguated from whatever
  they'd collided with. `AMBIGUOUS_EXACT` in the unmatched-games list dropped from 283 → 213
  accordingly. All 211 tests pass (2 new light-tier tests in `test_match.py`, including one
  proving the fix doesn't touch cases where light and aggressive tiers agree).
- **Not yet live**: same as the earlier matching-fix commits this session — the 35 newly
  recovered survivors are in the refreshed `data/matched_games.json`/`data/unmatched_games.json`
  but don't have Stage 3/4/5 data yet, so the main scored table and shortlist size are unchanged
  until the next `lookup-philibert.yml` dispatch.

## "Widen the net" round — three more real fixes, mined from the actual dropped/unmatched data
(2026-08-11)

User's follow-up, after seeing 621/4178: *"621 out of 4178 Zatu products still seems a very low
ratio."* Investigated by quantifying every drop reason first rather than guessing at fixes —
`data/dropped.csv` at the time: 1352 `QUALITY_GATE` (already-decided philosophy, not touched),
2191 `LOW_CONFIDENCE_MATCH`, further split via `data/unmatched_games.json`'s `match_category`
into 1537 `NO_CONFIDENT_MATCH`, 338 `MATCHES_EXCLUDED_EXPANSION` (real BGG expansions, correctly
out of scope per `include_expansions: false` — a scope question, not a bug), 213
`AMBIGUOUS_EXACT`, 21 `AMBIGUOUS_PREFIX`, 5 `DIGIT_CONFLICT`.

- **Ruled out lowering the fuzzy threshold globally, with real evidence, before touching
  anything**: sampled the real near-miss score bands. 85-90% is mostly genuine (Chicken Out!,
  EXIT titles), but below ~85% the false-positive rate climbs fast and is systemic, not
  occasional — many unrelated games share a generic suffix ("Kickstarter Edition", "Deluxe")
  that inflates `token_sort_ratio` with no real title similarity underneath (e.g. Zatu's "Calico
  Kickstarter Edition" was fuzzy-scoring 81.5% against BGG's completely unrelated "Autobahn:
  Kickstarter Edition" purely off the shared suffix). Confirms the existing 90 threshold is
  correctly calibrated, not overly conservative — the real opportunity was elsewhere.
- **Extended the targeted noise-stripping list** (`match.py`'s `_EDITION_NOISE_RE`), each word
  checked against the full real corpus first for collision risk before adding: "Kickstarter
  Edition", "Special Edition", "Base Game" (every real BGG title containing it pairs it with a
  distinguishing prefix, e.g. "Battlecrest: Fellwoods Base Game" — confirmed via the full
  9-entry real list, so stripping it can't merge two different products), and bare "Refresh"/
  "Refreshed" (a UK-retailer restocking/reprint term — confirmed via all 26 real Zatu titles
  containing it that it's never part of a game's actual name).
- **Added spelled-out ordinal edition handling** ("Second Edition" → the same abbreviated
  digit-ordinal form Zatu's own titles use, "2nd Edition") via a new `_ORDINAL_MAP`/`_ORDINAL_RE`
  conversion step run before both normalization tiers — the pre-existing edition-noise pattern
  only ever matched the digit form, so 1044 real BGG titles using spelled ordinals (17 real Zatu
  titles too) were previously untouched by it.
- **Caught and fixed a real regression from that ordinal change before it shipped**, same
  evidence-first method as every other fix this session: converting spelled ordinals initially
  broke `Gloomhaven 2nd Edition` — BGG catalogues `Gloomhaven` (id 174430) and `Gloomhaven
  (Second Edition)` (id 390478) as two separate, distinctly-priced entries (identical pattern to
  the earlier Carcassonne/Big Box bug), and bare-stripping "second edition" as noise at the
  aggressive tier collapsed that real distinction into a false ambiguity — while the light tier
  couldn't rescue it either, since it never converted BGG's spelled "Second Edition" to match
  Zatu's digit "2nd Edition" in the first place. Fixed by converting instead of stripping:
  ordinal conversion runs *before* either normalization tier, so the light tier can now exact-
  match "Gloomhaven 2nd Edition" to the *specific* Second Edition id — more precise than even
  the pre-regression behaviour, which would have fallen through to the base game's id.
- **A second, narrower regression from the same change, also caught before shipping**: a
  handful of real BGG titles use a *compound* ordinal for a single catalogued entry —
  `Mission: Red Planet (Second/Third Edition)`, `Fury of Dracula (Third/Fourth Edition)`, 5 total
  in `bg_ranks.csv`. Stripping only a single trailing ordinal left a stray leading ordinal token
  on the BGG side ("mission red planet 2nd") while the query's simple "Third Edition" stripped
  clean to "mission red planet" — an asymmetric strip that silently exact-matched the *wrong*,
  separate, lower-quality base-game BGG entry (id 18258, `usersrated`=4369, fails the quality
  gate) instead of the correct compound-edition entry (id 176920, `usersrated`=12477, passes).
  Fixed by extending the edition-noise regex to consume any number of slash-joined leading
  ordinals before the final one, so `"(Second/Third Edition)"` strips as a single unit on both
  sides — this specific game now correctly falls to the ambiguous-exact bucket (safe drop, per
  spec P2) rather than silently picking the wrong id.
- **Real, measured result of the noise-stripping + ordinal fixes together** (re-running
  `scripts/match_bgg.py` offline against the live corpus, before/after diffed by survivor
  handle+id, not just count): 621 → **635 survivors, net +14**. 16 real additions (Dominion:
  Second Edition, Eclipse: Second Dawn for the Galaxy, Twilight Imperium: Fourth Edition, War of
  the Ring: Second Edition, Camel Up (Second Edition), Fugitive (Second Edition), Parks (Second
  Edition), Calico/Cascadia Kickstarter Edition, Marvel United, Memoir '44, and others — all
  spot-checked as real, correct matches to specific BGG entries), 3 precision *improvements* on
  already-surviving handles (7 Wonders/Gloomhaven/Great Western Trail's "2nd Edition" SKUs now
  resolve to their specific BGG edition id instead of the base game's), 1 correct *removal*
  (Mission: Red Planet — the regression fix above, now safely ambiguous instead of wrongly
  matched), 0 unexplained regressions.
- **Ambiguous-exact dominance tiebreak — a deliberate, user-confirmed departure from spec P2**:
  mined the real 213-entry `AMBIGUOUS_EXACT` bucket against `bg_ranks.csv`'s own `usersrated`
  column and found most "ties" aren't real ties — e.g. "Coup" exact-matches 3 BGG entries (a
  1975 wargame, a 1991 wargame, and the actual 2012 game everyone means), `usersrated` 90 / 161 /
  52,695. A same-named entry with near-zero ratings was always going to fail the quality gate's
  own `min_votes` floor downstream anyway, so refusing the whole match over its mere existence is
  precision theatre, not real caution. Presented the real numbers to the user via
  `AskUserQuestion` rather than deciding unilaterally, since this is a genuine philosophy
  departure from spec P2's "ambiguous matches are dropped, never guessed" — **user confirmed
  "yes, add the dominance tiebreak."** Implemented as `BggIndex._dominant_by_rating_count`
  (`match.py`): when an exact-title match ties on 2+ BGG entries, pick the one with
  `usersrated` >= `_DOMINANCE_RATIO` (10x, chosen conservatively — 145/213 real cases clear it,
  and every spot-checked case at that bar had an obviously-dominant candidate, not a genuine
  coin-flip) times every other candidate's, returned as **MEDIUM** confidence (a picked answer,
  not a proven identity) rather than HIGH. A companion question about the 338
  `MATCHES_EXCLUDED_EXPANSION` products (real BGG-catalogued expansions, e.g. Wingspan: Oceania,
  Root: Riverfolk — correctly out of scope per `include_expansions: false`) was also asked;
  **user chose to keep expansions excluded, no change** — confirmed as a scope decision, not a
  bug, so left untouched.
- **Real, measured result of the dominance tiebreak**: 635 → **672 survivors, net +37** (40 real
  ambiguous ties resolved by dominance, 3 of those 40 then filtered back out by the pre-existing
  quality gate — expected, the tiebreak only decides *which* BGG entry a title means, it doesn't
  bypass the quality bar). Spot-checked a broad sample of the resolved ties: Sagrada, Watergate,
  Star Realms, Space Base, Tapestry, Cryptid, Akropolis, Paleo — all genuine, well-known,
  correctly-identified games that were previously being dropped purely because BGG happens to
  also catalogue an obscure, near-zero-rated same-named entry somewhere in its 179,794-row
  history. The one pre-existing `AMBIGUOUS_EXACT` case that does *not* auto-resolve even now
  (Mission: Red Planet, ratio ~2.85x, below the 10x bar) is correctly left as a genuine close
  call rather than guessed.
- **Session total: 621 → 672 survivors, net +51, zero unexplained regressions** across all three
  fixes (noise-stripping/ordinals, then the dominance tiebreak), each verified via a full
  before/after survivor-handle+id diff against the real 4178-product corpus, not just a raw
  count. All 220 tests pass (9 new: 6 `normalize_title` parametrize cases for the new noise
  words/ordinals, 1 light-tier ordinal-edition disambiguation test, 2 dominance-tiebreak tests
  covering both the resolves-clearly and still-drops-on-a-real-tie paths).
- **Not yet live**: same pattern as every matching-only fix this session — the net-new/
  id-changed survivors are in the refreshed `data/matched_games.json`/`data/unmatched_games.json`
  but don't have Stage 3/4/5 data (BGG French-edition check, EAN, Philibert lookup) yet, so the
  main scored table and shortlist size are unchanged until the next `lookup-philibert.yml`
  dispatch.

## Fuzzy-only down-weighting of generic marketing/edition words (2026-08-11)

User's direct follow-up: *"Let's remove or at least unweight some generic words like
kickstarter, edition, etc."* `_EDITION_NOISE_RE` already strips specific curated *phrases*
("kickstarter edition", "special edition") but a real corpus check found 128 real Zatu titles
still carry a bare "edition" after that — each paired with a one-off adjective too specific to
hand-list forever ("Citadels Revised Edition", "Mage Knight Boardgame Ultimate Edition",
"Sidereal Confluence: Remastered Edition"). Chose "unweight" over "remove" for *where* it
applies, not *whether* it strips: implemented as the same strip-to-noise mechanism already used
everywhere else in `match.py` (simplest, most testable, consistent with the rest of the
codebase — true fractional per-token weighting would need a custom rapidfuzz scorer for
uncertain gain), but scoped to a new location rather than folded into the existing
`normalize_title`/`_EDITION_NOISE_RE`.

- **Why a separate scope, not just extending `_EDITION_NOISE_RE`**: both exact-match tiers
  (light and aggressive) genuinely need words like "Big Box"/"Second Edition" in some cases —
  confirmed repeatedly this session that BGG catalogues real, separately-priced entries
  distinguished *only* by exactly these words (Carcassonne vs Carcassonne Big Box, Gloomhaven vs
  Gloomhaven Second Edition). Stripping a broader, more generic word list at that layer would
  reintroduce the same false-collision risk the light tier was built to prevent. The fuzzy tier
  is different: it only ever runs *after* both exact tiers already failed to find a specific id,
  so down-weighting words there to expose the substantive words underneath can't cause a wrong
  *identity* pick — worst case is a fuzzy score, still gated by the existing threshold/gap/
  digit-conflict checks exactly as before.
- **`match.py`**: new `_FUZZY_EXTRA_NOISE_RE` (kickstarter, edition, version, retail, special,
  standard, collector(s), anniversary, remastered, revised, definitive, ultimate, exclusive,
  complete, premium, essential(s), limited — each checked for corpus frequency first via the
  same `grep`-the-real-data method as every other word this session) and `_fuzzy_score_text()`
  applying it on top of the already aggressively-normalized string. `BggIndex.__init__`
  precomputes `self._fuzzy_names` (index-aligned 1:1 with `self.games`, so a fuzzy match found
  against the down-weighted string still looks up the correct game by position); `_match_fuzzy`
  scores `_fuzzy_score_text(norm)` against `self._fuzzy_names`, while the digit-conflict veto
  still checks the *original* `norm`/`best_norm` (down-weighting a word can never mask a real
  digit disagreement, since none of these words carry digits). Deliberately excluded "core"/
  "master"/"legacy" even from this broader list — all three are real, meaningful genre/product-
  line terms in this corpus (Pandemic *Legacy*, Marvel Champions *Core* Set, Summoner Wars
  *Master* Set), confirmed via the same corpus check, not marketing filler.
- **Real, measured result**: 672 → **678 survivors, net +6, zero regressions** (verified via the
  same full before/after survivor-handle+id diff against the real corpus as every prior fix).
  Smaller than the raw 128-title count because most of those 128 have some other complicating
  factor (a genuinely distinct themed variant, a name the base game doesn't share, etc.) — the 6
  recovered are exactly the ones that really were just marketing-word noise on top of an
  otherwise-exact title: `Compile Card Game: Main 1 Edition` → `Compile: Main 1`, `Everdell
  Farshore: Essential Edition` → `Everdell Farshore`, `Everdell Silverfrost: Essentials Edition`
  → `Everdell Silverfrost`, `Sidereal Confluence: Remastered Edition` → `Sidereal Confluence`,
  `Core Game (Deluxe Version) - The Witcher: Path of Destiny` → `The Witcher: Path of Destiny`,
  `Aspens` → `Aspens`. 2 new tests (`test_fuzzy_tier_downweights_bare_edition_word_to_recover_a_
  real_near_miss`, `test_fuzzy_tier_does_not_let_a_shared_generic_word_alone_create_a_false_
  match` — the latter reproducing the real Calico/Autobahn Kickstarter-Edition false-match risk
  directly, confirming the down-weighting doesn't *create* a false positive from a shared
  generic word either). 222 tests total pass.
- **Session-wide total after this round: 621 → 678 survivors, net +57** across all of this
  session's matching-coverage work, zero unexplained regressions at any step. Same "not yet
  live" caveat as above — needs the next `lookup-philibert.yml` dispatch for these to reach the
  actual shortlist/report.

## Live re-run bringing this session's matching work to the actual website (2026-08-11)

User: *"Let's now do the work to display them in the website. I don't care which edition it
is."* — dispatched `lookup-philibert.yml` (run 8, `0f87fd6` → `fb70bfc`, ~56 min) to carry all
678 survivors through Stage 3 (BGG French-edition check) → Stage 4 (EAN) → Stage 5 (Philibert)
→ Stage 6/7 (score + render), the same live pipeline documented above, just re-dispatched now
that this session's matching fixes are on `main`.

- **Real result**: 678 looked up → 479 `LISTED_IN_STOCK`, 163 `NOT_LISTED`, 36
  `FAMILY_LISTED_FR`. Verdicts: 466 `NONE`, 107 `FRENCH_EDITION_EXISTS`, 56 `UNAVAILABLE_FR`, 36
  `FAMILY_AVAILABLE_FR`, 13 `CHEAPER_UK`. **Shortlist: 58 → 69** (`UNAVAILABLE_FR` +
  `CHEAPER_UK`), live in `docs/index.html`.
- Top of the table now: **Gloomhaven 2nd Edition**, composite 80.9, `EXCELLENT` quality,
  `UNAVAILABLE_FR` — this session's own ordinal-edition fix (`match.py`'s `_ORDINAL_RE`) is what
  got it matched to BGG's specific "Gloomhaven (Second Edition)" entry in the first place; it
  wasn't reachable at all before this session's matching-coverage work. Also present: Resident
  Evil 3: The Board Game, Nusfjord Big Box, Blood Bowl: Third Season Edition, Vantage — all
  either dominance-tiebreak or noise-stripping recoveries from this session, now showing real
  Philibert price/availability data for the first time.
- No manual data massaging needed — the pipeline's own caching (Stage 4/5 skip anything
  already resolved from a prior run) meant this dispatch only paid live-network cost for the
  genuinely new/changed survivors, consistent with the caching work from earlier in this
  session.

## Manual Philibert title-override file, for real translations no heuristic can derive
(2026-08-11)

User-reported real miss: **EXIT: The Venice Conspiracy**
(`https://zatu.com/products/exit-the-venice-conspiracy`) is sold in France as **EXIT - Intrigue
à Venise** (`https://www.philibertnet.com/fr/iello/157939-exit-intrigue-a-venise-3701551704795.html`)
but was showing as `UNAVAILABLE_FR`/`NOT_LISTED` in `data/philibert_results.json`/
`docs/index.html`.

- **Root-caused, not just re-fixed the same way as prior title misses**: unlike the earlier
  Slay the Spire ("The Board Game" → "Le Jeu de Plateau") and Marvel Champions ("The Card Game"
  → "Le Jeu de Cartes") fixes, this isn't a fixed trailing-descriptor pattern — "The Venice
  Conspiracy" → "Intrigue à Venise" is a genuine, unpredictable subtitle translation ("Venice"/
  "Venise" aren't even spelled the same, "Conspiracy"/"Intrigue" share no characters at all).
  `_base_title_candidates()`'s fallback for this title is just "EXIT" (the part before the first
  colon), which correctly refuses to guess — the Philibert EXIT franchise has 12+ titles sharing
  that prefix, genuinely ambiguous.
- **Checked whether Stage 3's BGG French-edition data (`data/bgg_fr_editions.json`) already had
  the real title** (it did for Gloomhaven/Marvel Champions/Sherlock Holmes, extracted
  authoritatively from BGG's own versions page — see the Stage 3 section above) — it didn't:
  `bgg_id` 406312's entry is `{"fr_edition_exists": false, "fr_edition_titles": []}`. Likely a
  BGG catalogue-completeness gap for a 2024-released game rather than a bug in our scraper (BGG's
  own data is the limit here, not something this codebase can fix) — not verifiable further in
  this sandbox (BGG is network-blocked here, live-fetching only happens via GitHub Actions).
- **Chose a manually-maintained override file over a broader translation heuristic**: a blanket
  "try searching for just the franchise word" approach was considered and rejected — genuinely
  ambiguous (12+ EXIT titles alone) and unverifiable offline (no real Philibert search-result
  fixture data for the EXIT catalogue exists in this sandbox to test a heuristic against, per
  this project's own evidence-first standard for shipping matching logic). Instead, added
  `data/philibert_title_overrides.json` (new, `zatu_handle` → a human-confirmed real French
  title) — same plain-JSON, manually-maintained, never-auto-regenerated pattern as
  `data/excluded_games.json`/`data/bgg_fr_editions.json`. Directly fixes the reported case and
  gives a place to add more as the user finds them, without guessing.
- **`scripts/lookup_philibert.py`**: `lookup_one()` gained an `override_title` parameter, tried
  right after EAN search and ahead of the ordinary `zatu_title` search — a confirmed answer, not
  another guess to fall back to. `main()` loads the override file (`--title-overrides`, default
  `data/philibert_title_overrides.json`) and passes each survivor's override by `zatu_handle`.
  No workflow change needed — `.github/workflows/lookup-philibert.yml` invokes the script with
  defaults, so the new flag's default path is picked up automatically on the next dispatch.
- Added `data/philibert_title_overrides.json`'s first real entry: `"exit-the-venice-conspiracy":
  "EXIT - Intrigue à Venise"`. 2 new tests (`tests/test_lookup_philibert_script.py`): confirms
  `lookup_one()` tries the override title before the doomed real `zatu_title` search, and that
  `main()` wires the override file through by handle. 229 tests pass.
- **Not yet live** — same pattern as every Philibert-side fix this session: needs the next
  `lookup-philibert.yml` dispatch to confirm the override title actually resolves to the real
  listing on Philibert's live search (this sandbox can't reach philibertnet.com to verify).

## Unmatched-list filter, favorites, mobile UX modernization, BGG language dependence (2026-08-11)

User's follow-up, three asks in one message: (1) the "Not matched to BGG" list should only show
titles Stage 2 genuinely tried and failed to match, not ones dropped for an already-understood
reason (expansions etc); (2) a "favorite"/heart feature, same persistence model as "not
interested"; (3) a full mobile card UX pass — box art, a better-displayed rating, discount only
when meaningful, coop/party/duration shown as visible badges instead of buried in text, and (if
feasible) real BGG language-dependence data instead of the permanent UNKNOWN placeholder.

- **Unmatched-list filter** (`render.py`): `prepare_unmatched()` now only keeps
  `match_category == "NO_CONFIDENT_MATCH"` — `MATCHES_EXCLUDED_EXPANSION`/`AMBIGUOUS_EXACT`/
  `AMBIGUOUS_PREFIX`/`DIGIT_CONFLICT` all found a real BGG candidate and were declined for a
  specific, already-understood reason, not a genuine "we looked and found nothing" case.
  Display-only filter — `data/unmatched_games.json` itself stays untrimmed for transparency.
  Real effect: 1943 → 1511 shown. `scripts/render_html.py`'s summary line now reports both counts.
- **Favorites** (`data/favorited_games.json`, new — same manually-maintained, never-auto-
  regenerated pattern as `data/excluded_games.json`): a ♡/♥ toggle button on every row in BOTH
  the main scored table and the unmatched table (unlike "not interested", which stays scoped to
  the scored table only — favoriting is explicitly meant to work while eyeballing the unmatched
  list too, per the user's stated purpose "so I start creating a list"). One shared
  `localStorage` set (`ukbg_favorited_handles`) spans both tables since a handle only ever
  appears in one of them; each table gets its own "Only favorites (N)" filter checkbox, while
  Export/Clear are wired once at the top level against the shared set. `render.py`/
  `scripts/render_html.py` gained the same `favorited_handles`/`--favorited` plumbing as the
  hide feature. Verified live end-to-end with Playwright against the real report: toggle in
  either table, reload persistence, per-table "only favorites" filtering, export downloads the
  right `{"favorited_handles": [...]}` shape, and the global clear button resets both tables'
  counts/buttons in one action.
- **Mobile card redesign** (`templates/report.html.jinja2`, `render.py`), still scoped to the
  mobile breakpoint only per the user's own framing ("still only on mobile") — desktop table
  markup/behavior confirmed unchanged via a live 1400px Playwright check:
  - **Box art**: `sources/zatu.py` gained `extract_image_url()`/`fetch_product_image()` — Zatu's
    bulk harvest never captured an image at all (confirmed: `parse_product` only ever read
    handle/title/tags/variants), but the per-product detail endpoint Stage 4 already fetches for
    the EAN carries one for free. `scripts/enrich_zatu_ean.py` now fetches product detail once
    per survivor and extracts both `zatu_ean` and `zatu_image_url` from the same request (was
    two separate fetch paths for EAN alone; now genuinely one request, zero added network cost).
    Card shows the image when present, degrades to no image (not a broken-image icon) when
    absent — real image data needs the next live Stage 4 dispatch, not populated yet.
  - **Rating "well displayed"**: replaced the quality cell's wall of text
    ("8.05 shrunk · 8.2 raw · 3,400 votes") with a `★ 8.4` lead figure, a colored quality-label
    pill (EXCELLENT/STRONG/BORDERLINE/UNPROVEN/UNLABELED, one color per band), and the
    votes/shrunk detail demoted to a smaller secondary line.
  - **Discount only if meaningful**: confirmed via `advantage.py` that `discount_pct` is only
    ever non-null in the shortlist's `CHEAPER_UK` rows (`UNAVAILABLE_FR`/`OUT_OF_STOCK_FR` both
    hard-code `None`) — so "meaningful" was already true in the data, the actual problem was
    display: a "Discount: —" line was rendered on literally every non-`CHEAPER_UK` card (the
    large majority). Fixed by marking the `<td>` `is-empty` when `discount_pct`/`flags` are
    empty and hiding `.is-empty` cells only inside the mobile media query — desktop still shows
    "—" for column-alignment reasons, confirmed unaffected.
  - **Coop/party/duration/player-count, more visible**: previously only mentioned inline in the
    "why" sentence (coop/party) or not shown at all (duration/players — `clean_category_tags()`
    strips "N-M Minutes"/"N Players" as pure filter noise). Added `render.py`'s
    `extract_duration_tag()`/`extract_player_count_tag()` (reads the same raw `zatu_tags` list,
    just for *display* rather than the filter chips) and a `.game-badges` row of colored pills
    under the title, on both breakpoints.
  - **Language clause de-cluttered**: `build_why()` used to unconditionally append
    "language unknown" to every single card's why-line (100% of rows, since Stage 3 had never
    run) — user's explicit ask: "no need to say for all titles we don't know". Now the language
    clause (and the `UNKNOWN_LANG` badge) is omitted entirely when the level is unknown, and only
    shown when a real LOW/MED/HIGH value exists — ties directly into the language-dependence
    scraping below, which is what actually populates real values now.
- **BGG language-dependence scraping, built for real** (`sources/bgg_versions.py`): user's
  direct lead — a real BGG page (e.g. `/boardgame/437705/horrified-dungeons-and-dragons`) shows a
  "Language Dependence" community poll BGG itself is confirmed to render into a real headless
  browser's DOM (`scripts/probe_bgg_playwright.py`'s prior finding: "Language Dependence poll
  text present and extractable"). `parse_language_dependence(html)` extracts it from the *same*
  main-page load Stage 3 already does to resolve the title slug — zero extra navigations. Maps
  BGG's 5-point poll (`LANGUAGE_DEPENDENCE_LABELS`) to `score.py`'s existing LOW (1-2)/MED
  (3)/HIGH (4-5) scale, already designed generically for exactly this ("ready to pick up real
  values the moment Stage 3 lands, no signature change needed" — true, no changes needed to
  `score.py`/`score_games.py` at all).
  - **Deliberately markup-agnostic**: works off HTML-tag-stripped plain text, searching for each
    of the five official label phrases near the "Language Dependence" heading and reading the
    nearest adjacent integer as its vote count (checking both before and after the label text,
    since the real number/label ordering in BGG's actual rendered poll wasn't verifiable from
    this sandbox — see the caveat below). Picks the plurality (highest-vote) label, matching how
    BGG's own poll UI presents a "current consensus." Degrades to `language_level: None` (not a
    guess) whenever the heading or a countable label can't be found, so a markup mismatch fails
    silently into "unknown" — the same state every row was already in — rather than
    misclassifying a game.
  - **Explicitly NOT yet confirmed against a real captured page**: this sandbox cannot reach
    boardgamegeek.com (network-blocked, per this file's own top-level policy note), so
    `parse_language_dependence` is only unit-tested against a synthetic reconstruction of BGG's
    poll (`tests/test_bgg_versions.py`), not real markup — flagged inline in both the function's
    docstring and `enrich_bgg_fr_edition.py`'s module docstring. Needs a live GitHub Actions
    dispatch, then a manual spot-check of a handful of real results (e.g. does Horrified:
    Dungeons & Dragons come back with a sane level?) before this data should be fully trusted.
  - **Selection scope widened** (`scripts/enrich_bgg_fr_edition.py`): `fr_edition_exists` was
    deliberately narrow (only NOT_LISTED-on-Philibert survivors, since that's the only branch
    that reads it) — but `language_level` is read by every scored row's composite score, so
    `select_survivors_to_check()` changed from "NOT_LISTED or brand new" to "any bgg_id not yet
    fully cached" (missing `language_level` in its cache entry). Real cost consequence: the next
    live dispatch will need to visit closer to all ~678 survivors' bgg_ids (not the previous
    ~142), since none of the 237 already-cached entries have `language_level` yet — roughly
    678 × 2 page loads × ~13s ≈ 2-3 hours, a materially bigger run than any prior dispatch this
    project has done. Not yet dispatched — flagged for the user to confirm before kicking off a
    run this long.
  - **Wired through** `scripts/lookup_philibert.py`: each record now carries
    `bgg_language_level` read from `data/bgg_fr_editions.json` by `bgg_id` (same file/lookup
    `fr_edition_exists` already used) — `score_games.py`'s `score_one()` needed zero changes,
    exactly as its own prior docstring predicted.
  - 245 → 255 tests pass (10 new: 6 `parse_language_dependence` cases including two
    synthetic-poll fixtures, 2 `fetch_french_edition_info` integration cases confirming language
    data rides the existing page load with no extra navigation, 2 `lookup_philibert.py` wiring
    cases).

## Real matching misses from a user spot-check, and a real BGG API token (2026-08-12)

User reported 10 real "should have matched" titles (Citadels Revised Edition, BUS: Complete
Edition, Air Land & Sea: Revised Edition, Mycelia: Standard, Orleans Board Game: Big Box Edition,
Trailblazers Standard, Arkwright: Anniversary, Tenpenny Parks: Collector Edition, Raccoon Tycoon
Premium Edition, Living Planet Collector/Standard) with explicit framing: force a match unless
there's a genuine reason (a real separate "upgraded" BGG edition) to leave it unmatched on
purpose. Also pasted a real BGG API token in chat.

- **The token was never written to any repo file.** `docs/index.html` is served publicly via
  GitHub Pages, so anything committed here is world-readable — a credential belongs in a GitHub
  Actions secret (`Settings → Secrets and variables → Actions`), read only by workflows at
  runtime via `${{ secrets.BGG_API_TOKEN }}`, never printed or committed. Not yet wired into any
  workflow — the real `thing`/`search` BGG API (Bearer auth, spec's originally-intended Stage 3
  path) is a real, more-reliable-than-scraping alternative to `sources/bgg_versions.py`'s
  headless-browser approach now that a token exists, but building that out is separate work, not
  done in this round.
- **`match.py` gained three real additions**, each corpus-checked against the full
  140,261-base-game corpus before shipping (same method as every prior noise-word fix this
  project has made) — not just checked against the 10 reported titles:
  - `_COLLECTOR_RE`: "collector's"/"collectors" → "collector", applied in both normalize tiers
    before punctuation stripping. Real fix: BGG's own "Tenpenny Parks: Collector's Edition" only
    differs from Zatu's "Tenpenny Parks: Collector Edition" by this apostrophe-s.
  - `_LIGHT_SAFE_FILLER_RE` (light tier only, NOT the aggressive tier): bare "edition" and "the
    game". Corpus-checked in isolation first (16 and, once properly checked *in combination*
    with "the" already being stripped by `_ARTICLE_RE`, 90+ collisions respectively — both
    turned out to be safe in practice: nearly all are BGG-side near-duplicate listings or cases
    where the existing rating-dominance tiebreak (see below) already resolves them correctly,
    since "the game" was already being stripped at the *aggressive* tier for years before this
    session). **Deliberately excludes "board game"/"card game"** despite looking like the same
    kind of filler (needed for the Orléans Big Box case below) — a full-corpus check found 123
    and 455 real collisions respectively, including a genuine wrong-match risk: "Arkwright: The
    Card Game" is a real, separate spin-off product (not an edition of base Arkwright) that
    would have silently collided with it. Confirmed via a direct before/after regression check
    that excluding these two words preserves that game's own correct light-tier resolution.
  - `_RECENCY_SIGNAL_RE` + `BggIndex._recency_pick()`: when an exact match ties on **multiple
    BGG entries sharing the identical bare name** (BGG catalogues "Citadels" twice — id 478,
    2000, and id 205398, 2016's Revised Edition, with no distinguishing word in either BGG name
    at all) and the query's own raw text says this is a newer printing ("revised"/"anniversary"/
    "renewed"/"remastered"/"reprint"), pick the tied candidate with the latest `yearpublished` —
    tried at both the light and aggressive exact-tie points, after the existing rating-dominance
    tiebreak (which alone picks *wrong* here: 2000's original has more cumulative ratings simply
    from being older, 57379 vs 17553, and neither clears the existing 10x dominance bar anyway).
- **A real regression found by re-running the full match, not just spot-checking the 10 titles**:
  stripping "edition"/"the game" at the light tier turned some *other*, previously-clean
  single-candidate light matches into new ties against a real BGG variant edition (e.g. "Galaxy
  Trucker" vs "Galaxy Trucker: Anniversary Edition") — a title that used to resolve correctly
  only because the light tier happened not to see the collision at all. Root-caused via a direct
  before/after diff of the real 4178-product match output (not assumed from the corpus check
  alone). Fixed by trying the light tier's own dominance-tiebreak (identical logic to the
  aggressive tier's, just applied one tier earlier) before falling through — confirmed via the
  same before/after diff that this fully recovers the one real case found (Galaxy Trucker (2021)
  → base Galaxy Trucker, 35880 vs 2961 ratings, same result as before this session's changes).
- **Real, measured result** (re-running `scripts/match_bgg.py` offline against the live 4178×
  140,261 corpus, before/after diffed by survivor handle+id): 678 → **682 survivors, net +4**.
  5 real additions: `air-land-sea-revised-edition`→247367, `arkwright-anniversary`→154825,
  `citadels-revised-edition`→205398 (the actual 2016 Revised Edition, not the more-rated-but-
  wrong 2000 original — confirms the recency-tiebreak over dominance-alone), plus two bonus
  recoveries the noise-word fixes caught beyond the reported 10:
  `werewords-deluxe`→"Werewords Deluxe Edition" and `explorers-of-the-north-sea-collector-...`→
  "Explorers of the North Sea". 1 removal, `leaf-deluxe` — not a regression: it now correctly
  identifies as the real, separate "Leaf: Deluxe Edition" BGG entry (previously wrongly compared
  against base "Leaf"'s price/quality) and correctly fails the quality gate on its own low BGG
  vote count (45 users) — a precision fix, same shape as the earlier Terraforming Mars
  Ares-Expedition-Crisis bug this project already fixed once before.
- **5 of the 10 reported titles are genuinely unresolved, confirmed via real BGG data, not
  guessed past**:
  - **BUS: Complete Edition** — BGG has two entries both literally named "Bus"/"BUS": the 1999
    Alea classic (id 552, 5556 ratings) and an obscure 2015 game (id 164159, 764 ratings, ratio
    ~7.3x, just under the 10x dominance bar). Not an edition/revision relationship at all, just
    two different games sharing a name — no safe way to auto-pick.
  - **Mycelia: Standard** — BGG has two entries both literally "Mycelia" (2023 vs 2024, no
    distinguishing text in either name) and "standard" isn't a recency signal (doesn't mean
    "newer"), so the tiebreak correctly doesn't fire.
  - **Orleans Board Game: Big Box Edition** — the fix that would catch this (stripping "Board
    Game"/"Card Game" as filler) is the one deliberately excluded above for real corpus-collision
    reasons (Arkwright: The Card Game). Needs a narrower, one-off fix (or a manual override, same
    pattern as `data/philibert_title_overrides.json`), not attempted this round.
  - **Raccoon Tycoon - Premium Edition / Living Planet Collector** — both have a real BGG
    "Deluxe Edition" entry as a separate product, but neither Zatu title says "Deluxe" — whether
    "Premium"/"Collector" is Zatu's own name for that same Deluxe product or genuinely a
    different (base-tier) SKU can't be determined from title text alone; a wrong guess here means
    comparing the wrong product's price, exactly the failure mode this project's precision-first
    design exists to avoid.
- 2 new tests in `tests/test_match.py` (light-tier resolution of "Citadels Revised Edition",
  replacing an now-obsolete fuzzy-tier expectation for the same title). 256 tests total pass.
- **Not yet live** — same pattern as every Stage 2-only fix this session: the 5 newly-recovered
  survivors are in the refreshed `data/matched_games.json`/`data/unmatched_games.json` but don't
  have Stage 3/4/5 data yet, so the scored shortlist and rendered report are unchanged until the
  next `lookup-philibert.yml` dispatch.
