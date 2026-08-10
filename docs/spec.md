# Board Game "Buy in the UK?" Advisor — Specification v1.0

> One-off personal tool. Goal: from Zatu's catalogue, produce a **ranked list of every game that passes
> the criteria** worth buying during a UK trip — good games, hard to get or much pricier in France,
> ideally coop/party, ideally low-language-dependence. The list is not capped; the person drills down as
> far as the actual result count warrants, and makes a final human choice of 0–3 games.
>
> v1.0 incorporates all decisions from the review round. Remaining unknowns are marked **[VERIFY]**
> (facts to check during build, not choices to make).
>
> v1.1 adds §0, the access investigation, and folds its findings into Stages 0/2/4/5. Given a note
> about **limited internet access while coding**, §0.4 separates what must happen online now
> (BGG registration, a manual bulk download) from what the tool itself will fetch at build/run time.
>
> **Verified 2026-08-10, from inside the actual coding environment:** the "limited internet access"
> isn't flaky Wi-Fi, it's a fixed network policy. Direct `curl` tests to `zatu.com`,
> `boardgamegeek.com`, `philibertnet.com` (both with and without `www.` — the original test here
> mistakenly cited `philibert.net`, a different, wrong domain; corrected once the mistake surfaced
> via a 404 in a live GitHub Actions probe), and `1jour-1jeu.com` all get rejected at the gateway
> (`403` on `CONNECT`) — this coding sandbox cannot reach any of the three target sites, full stop.
> Package registries (PyPI, npm) and GitHub work fine, so `pip install` and git push/pull are
> unaffected. This *confirms* §0.4's "code offline, run online" plan is the right one, but sharpens
> the reason: it's not that connectivity might improve once the developer sits down to code, it's
> that **this environment specifically will never reach those sites**, however long you wait.
> Practical upshot: build and unit-test Stages 0–2/6/7 here against the §11 fixtures as planned; run
> the live-fetching stages (0/3/4/5 against real endpoints) from a machine or environment that isn't
> network-policy-restricted to those hosts — e.g. the developer's own machine, or a Claude Code
> environment whose network policy is configured to allow them.

---

## 0. Access & feasibility investigation (do this first)

Checked directly: BGG's API documentation, Zatu's live site, and Philibert's live site. Findings below
replace the earlier guesses in the v1.0 draft; §§2–7 have been updated to match.

### 0.1 BoardGameGeek — **a token is required**, and approval is slow

This is the one correction that matters most for planning: **yes, you need to register an application
and get a Bearer token** — the earlier "maybe token-free" framing was wrong. BGG's current policy
states plainly: *"Registration and authorization is required for use of the XML API… Registration is
required for nearly all use of the XML API."* Every `thing`/`search` call needs an
`Authorization: Bearer <token>` header, or it's rejected outright. This part of the policy is
unambiguous — unlike the CSV question below, there's no conflicting text to weigh. **[VERIFY, live
behaviour only]** I confirmed this from BGG's published policy text, not by hitting the live endpoint —
`xmlapi2/thing` is a dynamic API URL that doesn't surface through search, so I couldn't fetch it
directly to see the exact HTTP status/error body a token-less request gets back. Code the auth-failure
path defensively (expect 401/403, log the raw response) and treat your first real authenticated call as
the actual confirmation, not this document.

**Action for you, this week, regardless of when you start coding:** go to
`https://boardgamegeek.com/applications`, register a non-commercial application, and generate a token.
BGG's own text warns *"it may be a week or more before we get back to you."* If you register today,
the token should be ready well before the trip; if you wait until you sit down to code, it may not be.

Two access modes end up mattered differently:

- **Bulk ranked-games CSV** (`boardgamegeek.com/data_dumps/bg_ranks` — id, name, year, rank, average,
  bayesaverage, usersrated for every game). BGG's own text is **internally inconsistent**: one section
  says *"you do not need to register to download the CSV dump of all games while logged in"*; another
  says an *"approved application… will be required for the CSV download."* Rather than resolve the
  ambiguity in code, sidestep it: **log into your BGG account in a normal browser and download the CSV
  by hand, once, ahead of time.** That's explicitly permitted under the first clause, needs no token,
  and produces a static file the offline Stage 2 match/quality-gate can run against with zero further
  BGG traffic. Re-download every few weeks if you like — ranks drift slowly.
- **`thing`/`search` endpoints** (mechanics, language-dependence poll, versions/French edition) —
  **do** need the Bearer token, no way around it. This is Stage 3, and only runs for the few hundred
  games that survive Stage 2, so total call volume is modest.

Other confirmed mechanics: `thing` accepts **max 20 ids per call** (batch accordingly); a cold request
can return **HTTP 202** while BGG queues it server-side (poll with backoff until 200); BGG asks for a
**5-second gap between requests** as a courtesy rate limit — slower than generic scraping, but Stage 3's
volume is small enough that this is a non-issue, not a bottleneck.

**If the token doesn't arrive in time — a real fallback exists, and it only affects Stage 3.** Stage 2's
quality gate runs entirely off the manually-downloaded CSV and needs no token at all, so the core ranking
is never blocked. For Stage 3 specifically (mechanics, language dependence, French edition/versions),
BGG's own **public game pages** expose the same fields in plain HTML with no login or token — confirmed
live: a real game page shows a `Language Dependence` widget with a link to the full poll, mechanics/
category tags in the sidebar, and a versions/language-editions list, all in ordinary page markup. This
is the same category of scraping already planned for Zatu and Philibert, just a third adapter of the
same kind — not new engineering, just more of it. Note this shifts you from the *XML API's* terms to the
site's general terms, a different (and less explicit) policy surface; treat it with the same politeness
budget as the other two sources (rate-limit, cache, one-time low-volume run) and don't rely on it as a
long-term integration. **Design recommendation regardless of which path you take:** make Stage 3 a
best-effort enrichment, not a hard dependency — the tool should produce a full ranked list from Stages
0–2 alone (quality-gated, but no coop/party bonus or language signal) if Stage 3 data isn't available
yet, then backfill once the token or the HTML fallback comes through. That turns "no token in time" into
a minor quality reduction on the first run rather than a blocker.

### 0.2 Zatu — good news: it's Shopify, and that changes Stage 0 and Stage 4

Confirmed live: Zatu (`zatu.com`, formerly/also `board-game.co.uk`) runs on **Shopify** — visible from
`cdn.shopify.com` asset URLs, a `zatu-games.myshopify.com` backing domain, and a "Powered by Shopify"
footer. This matters because Shopify storefronts universally expose **free, public, unauthenticated
JSON** — no account, no key, no scraping HTML for basics:

- `https://zatu.com/products.json` and `/collections/<handle>/products.json` — paginated structured
  JSON per product: title, price, availability, and (often) a `barcode` field on each variant, which is
  frequently the **EAN** — a much stronger match key than fuzzy title matching. **[VERIFY]** whether
  Zatu populates `barcode`; if so, it upgrades Stage 4/§4 matching significantly.
- **A ready-made, already-curated collection:** `https://zatu.com/en-us/collections/top-5000-board-games`
  — board games only, no manual category filtering needed. This likely **replaces most of Stage 1**
  (the non-game filter) outright.
- Standard `/sitemap.xml` also exists on essentially all Shopify stores as a platform default, as a fallback
  discovery path.

**One real gotcha, worth flagging clearly:** the storefront is geolocation/locale-aware — fetching it
without a UK context returned **USD pricing** in this investigation, not GBP. Shopify sites like this
typically use "Shopify Markets," where currency depends on a locale path segment (e.g. `/en-gb/`), a
`?country=` parameter, or a cookie. **[VERIFY]** the exact mechanism before trusting any scraped price —
getting this wrong would silently corrupt every `CHEAPER_UK` computation in §5.2. The unauthenticated
`/products.json` endpoint may return prices in the shop's base currency regardless of locale, which
would sidestep the problem entirely — check this first, it may make the whole issue moot.

Net effect: **Stage 0 and Stage 4 both get simpler and more reliable** than the original HTML-scraping
plan — pull JSON, not pages.

### 0.3 Philibert — PrestaShop, no bulk export, but a genuinely useful quirk

Confirmed live: Philibert (`philibertnet.com`) runs on **PrestaShop**, visible from its
`/fr/<category-id>-<slug>` and `/fr/<brand>/<product-id>-<slug>-<code>.html` URL patterns. Unlike
Shopify, PrestaShop has **no public bulk JSON catalogue export by default** — so Stage 5 still needs
either the on-site search or per-product page fetches, roughly as planned. No login or key needed to
browse or search; it's a normal public storefront.

**Confirmed on a real product page — and better than the original plan assumed.** A live fetch of an
actual product (`/fr/iello/171597-athletes-de-compete-3701551706461.html`) showed the data rendered as
**plain server-side text**, no JavaScript required — plain `requests` + BeautifulSoup is enough:

```
Français · à partir de 6 ans · moins de 30mn · 2 à 6 joueurs
Précommande : Fin aout/début septembre        ← availability + restock note
26,90€                                         ← price

Fiche technique
  Langue(s)     Français        ← edition's actual language, stated directly
  EAN           3701551706461   ← clean labeled field, not just URL-embedded
  Editeur       Iello
Référence : IEL-70646           ← Philibert's internal SKU (≠ EAN, like Zatu's SKU)
```

Two upgrades from the original plan worth building around: the **EAN sits in a clean labeled field**
(`EAN <13 digits>` under "Fiche technique"), which is a more robust extraction target than parsing it
out of the URL — use both, URL as a fast pre-filter and the field as the authoritative value. And
Philibert states the **edition's actual language directly** (`Langue(s): Français`), which is a more
direct FR-availability/localisation signal than inferring it indirectly through BGG's version data —
use it as the primary check and keep the BGG cross-check (below) as a secondary corroboration only.

**One caveat, now precisely scoped rather than a general worry:** a literal, unrendered template string
(`product.oos`) does appear in the raw HTML — but only inside the small cross-sell widgets ("Produits
associés" / "Accessoires", e.g. other-language editions or add-on accessories), not in the primary
product's own data block. Parse only the main product's "Fiche technique" section for stock/price/EAN;
never treat those secondary cards as a stock-status source. **[VERIFY, still open]** the exact string
used for the primary product's own *out-of-stock* state — this session only observed a pre-order
(`Précommande`/`Précommander`) and, by contrast, in-stock items elsewhere on the site simply show an
active `Ajouter au panier` button; the precise wording for a sold-out primary product wasn't hit. Cheap
to confirm with one real request once you're coding with a connection — search Philibert for something
known to be sold out and check what the button/label says.

**False-positive guard (the BGG cross-check):** `NOT_LISTED` is the highest-value verdict, so it gets
corroborated. If BGG shows **no French edition has ever been published**, `NOT_LISTED` is credible →
full confidence. If a **French edition does exist** but Philibert shows nothing, it's more likely a
matching miss → downgrade confidence and tag the row `NEEDS_EYEBALL`. This is now a secondary check,
not the primary one — Philibert's own `Langue(s)` field (above) is the more direct signal when a match
is found at all.

**Optional, not core:** `1jour-1jeu.com` (and `en.1jour-1jeu.com`) is a long-running French board-game
price-comparison site that already aggregates Philibert plus ~20 other FR retailers, per-game, including
language info. It's a free corroborating signal if Philibert's own search comes back empty — worth a
try-and-fallback, not a dependency to build around.

### 0.4 What this means for your setup: **code offline, run online**

Correcting my earlier assumption — the constraint is internet access **while writing code**, not while
*running* it. That's actually the easier version of this problem: the finished tool can just do all its
live fetching normally when you run it, with no need to design around flaky connectivity, resumability,
or partial runs. What it does mean:

- **You'll be writing HTTP-calling code without being able to call the endpoints to check what comes
  back.** The single highest-value thing to do about that is have real (or accurately representative)
  sample payloads to code against — §11 below has them, captured live in this session.
- **`pip install` also needs internet.** Install everything before you lose connectivity: `requests`,
  `beautifulsoup4` or `lxml`, `rapidfuzz`, `pandas`, `jinja2`. Trivial to forget since it's a separate
  moment from "writing the code."
- **The BGG token wait is still worth starting today** — not because of your connectivity, but because
  BGG's own approval turnaround ("a week or more") is a fixed external delay independent of when you
  code or run the tool. Register now regardless.
- **The CSV download (§0.1) has no urgency from the connectivity angle either** — do it whenever's
  convenient before your first real run, since that run will have internet anyway.

Practically: build and unit-test the matching/scoring/rendering logic (Stages 1, 2, 6, 7) offline against
the fixtures in §11, then do a single connected run for Stages 0/3/4/5 whenever you have internet — no
special offline-mode design needed in the code itself.

---

## 1. Design premises (these drive everything)

Three consequences of the answers given, stated up front because they shape every later section:

**P1 — Zatu is the universe, not a lookup.** With no wishlist, the candidate set *is* Zatu's catalogue.
Everything flows outward from there. A game not sold by Zatu is out of scope by definition.

**P2 — No human in the loop per game during matching; full results shown, human drills down at the end.**
Thousands of candidates make per-game match *confirmation* impossible, so matching stays biased toward
**precision** — ambiguous matches are dropped rather than surfaced (§4.2). That's a matching-stage rule,
not a display cap: every game that survives the quality gate and has a genuine UK advantage appears in
the output, however many that turns out to be. The person sorts/filters/scrolls to decide how deep to
look, rather than the tool guessing a cutoff for them.

**P3 — Cheap wide pass, expensive narrow pass.** Filter on free/cheap data first (catalogue titles,
one BGG bulk file), and only make per-page HTTP requests for the small surviving set. This is what
makes the whole thing tractable *and* keeps the fragile scraping surface small.

---

## 2. Pipeline overview

```
STAGE 0  Zatu JSON harvest           /collections/top-5000-board-games/products.json  1–2 dozen paged fetches
              │                      (Shopify, public, no auth)          ~most of the board-game catalogue
              ▼
STAGE 1  Board-game filter           light cleanup only — Stage 0's collection is already game-scoped
              │                                                          → most rows already survive
              ▼
STAGE 2  BGG bulk match (OFFLINE)    match titles vs pre-downloaded bg_ranks.csv (§0.1)
              │                      + drop expansions, apply QUALITY GATE       no network calls
              │                                                          → ~200–600 survivors
              ▼
STAGE 3  BGG enrich (per game)       thing?id=…&stats=1&versions=1   [needs Bearer token, §0.1]
              │                      mechanics, language poll, FR edition exists?
              ▼
STAGE 4  Zatu detail (per game)      price GBP (locale-forced, §0.2), stock, EAN — from JSON, not HTML
              ▼
STAGE 5  Philibert lookup (per game) EAN search first (§0.3) → title search fallback; listed? stock? price
              ▼
STAGE 6  Advantage + scoring         compute advantage, quality, bonuses, composite
              ▼
STAGE 7  Static HTML output          sortable table, full result set, source links
```

Stage 0 is now JSON, not HTML — Shopify's public storefront API does the heavy lifting. Only Stage 5
(Philibert) still needs page fetches by default, since PrestaShop has no equivalent bulk export.

---

## 3. Stage detail

### Stage 0 — Zatu JSON harvest
- **Primary method:** page through `https://zatu.com/en-us/collections/top-5000-board-games/products.json?limit=250&page=N`
  (Shopify's standard storefront JSON, public, no auth) until an empty page. Each product includes
  title, handle/URL, and per-variant price/availability/`barcode`. **[VERIFY]** the collection's exact
  handle and page count; confirm the currency returned (§0.2) before trusting prices at this stage —
  if `/products.json` isn't locale-sensitive, prices here may already be usable directly.
- **Fallback:** generic `/products.json` across the whole store, or `/sitemap.xml`, if the curated
  collection turns out incomplete.
- **Output:** `{url, title, barcode?, price_raw, in_stock}` rows → cached to local JSON/SQLite.

### Stage 1 — Board-game filter
Since Stage 0 now pulls from a pre-curated board-games-only collection, this becomes light cleanup
(drop obvious accessories/bundles by title keyword) rather than the heavier category filtering
originally planned — Stage 2's BGG match remains the real gate regardless.

### Stage 2 — BGG bulk match + quality gate (the key optimisation)
- **Source:** the `bg_ranks` CSV **downloaded by hand ahead of time** per §0.1 (id, name, year, rank,
  average, bayesaverage, usersrated) — a static local file, not a live call. No token needed for this
  step since it's not touching the API at all.
- **Match offline** (see §4) — no network cost, so it can be generous in trying variants.
- **Drop expansions** (`type=boardgameexpansion`) and accessories — you're buying playable boxes.
  *Exception:* keep expansions only if a future flag enables them; off by default.
- **Apply the quality gate here** (see §5.1) so everything downstream is already worth the effort.

### Stage 3 — BGG enrich
`GET /xmlapi2/thing?id=<batched ids>&stats=1&versions=1` with header `Authorization: Bearer <token>`
(§0.1 — this is the one stage that hard-requires the registered application).
- Batch **max 20 ids per call** (BGG's documented limit). Handle **HTTP 202 (queued)** with exponential
  backoff. Respect the **5-second gap** between requests BGG asks for. Cache permanently.
- Extract:
  | Field | Path | Purpose |
  |---|---|---|
  | average, usersrated, bayesaverage | `statistics/ratings/…` | Quality score |
  | mechanics | `link type=boardgamemechanic` | **coop** = "Cooperative Game" |
  | categories | `link type=boardgamecategory` | **party** = "Party Game" |
  | language dependence poll | `poll name="language_dependence"` | Criterion 4 |
  | versions | `versions/item` | **FR edition exists?** + French title |
  | playing time, player count, weight | `minplayers`, `playingtime`, `averageweight` | Display context |

- **Language dependence:** take the weighted plurality level (1–5). Poll often has few votes on
  obscure games → if total votes < 5, mark `UNKNOWN` rather than trusting it.
- **French title harvest:** scan `versions/item` for versions linked to French language; capture their
  names. Feeds Stage 5's second query and the FR-edition-exists signal.

### Stage 4 — Zatu product detail
For most surviving games this is **already satisfied by Stage 0's JSON** (§0.2) — price, stock, and
`barcode` came back in the initial harvest. This stage is only a per-product fetch for the minority
where the collection JSON was incomplete or a variant needs disambiguating (e.g. confirming which SKU
is the standard retail edition vs. a big-box). Confirm GBP currency per §0.2 before use either way.

### Stage 5 — Philibert lookup
Per surviving game: **if an EAN is known** (from Zatu's `barcode`), search Philibert by EAN first and
confirm by checking the **labeled `EAN` field in the product's "Fiche technique" block** (§0.3 — more
robust than the URL pattern, which is a good fast pre-filter but secondary). **Otherwise**, fall back to
query search with **(a) English title**, then **(b) French title(s)** from BGG. Either path, extract
`Langue(s)` from the same block as the primary FR-language signal (stronger than inferring it via BGG),
and classify into exactly one:
- `NOT_LISTED` — no plausible result for either query
- `LISTED_OUT_OF_STOCK` — matched product, unavailable
- `LISTED_IN_STOCK` — matched product + `price_eur`

**False-positive guard (the BGG cross-check):** `NOT_LISTED` is the highest-value verdict, so it gets
corroborated. If BGG shows **no French edition has ever been published**, `NOT_LISTED` is credible →
full confidence. If a **French edition does exist** but Philibert shows nothing, it's more likely a
matching miss → downgrade confidence and tag the row `NEEDS_EYEBALL`. This costs nothing (data already
fetched) and prevents the most likely way the tool would mislead you.

### Stage 6 — Scoring
See §5.

### Stage 7 — Output
See §6.

---

## 4. Matching strategy (no human in the loop)

### 4.1 Normalisation (both sides)
Lowercase; strip accents/diacritics; strip edition/marketing noise (`board game`, `card game`,
`2nd edition`, `deluxe`, `big box`, `retail edition`, `english`, publisher names); normalise `&`→`and`,
roman numerals, punctuation, articles; collapse whitespace.

### 4.2 Confidence cascade
| Tier | Rule | Action |
|---|---|---|
| **HIGH** | **EAN match (Zatu `barcode` ↔ Philibert URL-embedded EAN, §0.2–0.3)**, or exact normalised title (+year within ±1 if both known) | auto-accept |
| **MEDIUM** | fuzzy score ≥ threshold **and** clear gap to 2nd-best candidate **and** unique | auto-accept, tagged |
| **LOW** | fuzzy below threshold, or two candidates too close together | **silently drop** |

Per **P2**, LOW is dropped, not queued. Rationale: with only 0–3 purchases needed, recall loss is
acceptable and precision protects the shortlist's credibility. Rejected candidates are still written
to a `dropped.csv` so you can skim it once if you're curious.

### 4.3 Known traps
- **Base vs expansion** — filtered at Stage 2 by BGG type.
- **Same name, different game** — disambiguate on year; if still ambiguous, drop (LOW).
- **Renamed French editions** — solved by querying Philibert with BGG's French version titles.
- **Deluxe/Kickstarter vs retail SKUs** — different prices for "the same" BGG id; keep the cheapest
  in-stock standard edition, flag if a variant was chosen.
- **Bundles/multi-packs** — detect by keyword; exclude from price comparison.

**Verified 2026-08-10, real Stage 2 run (4178 Zatu products × 140,261 BGG base games, 576
survivors):**
- **"Disambiguate on year" doesn't happen yet** — Zatu's harvested data has no reliable year
  field, so the "same name, different game" trap currently always resolves to LOW/drop rather
  than a year-based pick. 264 exact-title + 25 prefix-title drops were this case (`Carcassonne`,
  `Everdell`, `Dominion 2nd Edition`, etc. — base game vs Big Box vs expansion editions all
  sharing one normalized title or prefix). Correct per this section's own fallback rule ("if
  still ambiguous, drop"), just confirms year-disambiguation is a real gap, not yet a real
  feature.
- **A plain fuzzy scorer is not safe on its own** — empirically, `rapidfuzz`'s `WRatio` scores an
  expansion's title against its own base game (`"Spirit Island: Branch & Claw"` vs `"Spirit
  Island"`) at exactly 90.0 due to partial-ratio weighting, and even a stricter scorer
  (`token_sort_ratio`) scores `"Pandemic Legacy: Season 1"` vs `"Season 2"` at ~96% despite being
  different games. §4.1/§4.2 as written don't anticipate either failure mode. `match.py` switched
  scorers and added an explicit digit-conflict veto (any query/candidate pair where both sides
  carry digit tokens that differ is rejected outright, regardless of score) — 4 real drops were
  this veto firing correctly (e.g. Zatu's "UNO Toy Story 5" correctly refused a fuzzy match to
  BGG's "UNO: Toy Story 3"/"4").
- **§4.1's normalisation needed three additions**, each found by running the real match, not
  fixture data: HTML-entity unescaping (8 real Zatu titles had literal `&amp;`), stripping a
  thousands-separator comma from numbers before tokenizing (BGG writes `"Warhammer 40,000"`,
  Zatu writes `"40000"` — 463 BGG titles affected), and stripping a trailing `"(2013)"`-style
  release-year annotation (18 real Zatu titles carry one, no BGG counterpart does). Also found
  and fixed a bug where `"core"` was stripped as a bare noise word (added for "Spirit Island
  (Core Game)"), which silently ate the word out of "Company of Heroes: 2nd Edition **Core
  Set**" — a real BGG product-line term. Only the "core game" phrase is stripped now.
- **§4.2's confidence cascade is missing a real, common case**: a retailer shortening a title by
  dropping the BGG subtitle (Zatu's "Five Tribes" for BGG's "Five Tribes: The Djinns of Naqala").
  This isn't a fuzzy-match problem — dropping most of the candidate's text tanks any
  string-similarity score — so added a fourth tier, tried only as a fallback after exact+fuzzy
  both fail (purely additive, can't regress an existing decision): a query that's a unique
  word-boundary prefix of exactly one BGG title is accepted at MEDIUM confidence; a prefix shared
  by multiple BGG titles (e.g. "Suspects" against 14 different "Suspects: <subtitle>" entries) is
  still dropped as ambiguous, same philosophy as the exact-match tier. +18 net survivors on the
  real data (19 new prefix matches, one of which then correctly failed the quality gate); all 19
  manually spot-checked against the real matched output, no false positives found.

---

## 5. Scoring model

Composite = `advantage + quality + genre + language`. Every component stays a visible column.

### 5.1 Quality gate & score (criterion 2) — *shrunk rating*
Straight thresholds create a cliff (7.49 with 5,000 votes losing to 7.51 with 100 votes) and treat
vote count as a switch rather than a signal. Instead, votes shrink the rating toward a neutral prior:

```
shrunk = (usersrated × average + M × PRIOR) / (usersrated + M)
        with M = 100 (vote-count anchor), PRIOR = 6.5 (neutral game)
```

A 8.4-rated game with 60 votes lands near 7.7 (promising but discounted); with 6,000 votes it stays ~8.4.
Few votes therefore *automatically* means a more cautious score — no separate rule needed.

**Verified 2026-08-10, implementing `score.py`:** plugging this section's own numbers into its
own formula gives `shrunk = (60×8.4 + 100×6.5) / (60+100) = 7.2125`, not the "~7.7" stated above —
the worked example is an imprecise approximation, not a second, different value the formula is
supposed to hit. Implemented literally as the formula states (confirmed correct against the
6,000-vote case, which does land at ~8.37 as described). If "~7.7" was actually the intended
target, `M` would need to be 35, not 100 (solving `(60×8.4 + M×6.5)/(60+M) = 7.7` gives
`M = 35`) — worth a second look if the gate ever feels too harsh on lightly-voted games in
practice; `M=100` shrinks noticeably harder toward the 6.5 prior than the prose implies.

- **Gate:** drop if `shrunk < 7.2` **or** `usersrated < 30`. (7.2 shrunk ≈ your "7.5 raw with decent
  evidence" line, while letting a very strong, well-rated game through despite modest votes.)
- **Points:** `quality_pts = clamp((shrunk − 7.2) / (8.6 − 7.2), 0, 1) × 45`

**Displayed label** (your original bands, kept for readability — labels only, not logic):
`EXCELLENT` ≥8.0 & ≥100 votes · `STRONG` ≥7.5 & ≥100 · `UNPROVEN` ≥8.0 & <100 · `BORDERLINE` ≥7.5 & <100.

### 5.2 UK advantage (criterion 1) — near-gating
| Verdict | Condition | Points |
|---|---|---|
| `UNAVAILABLE_FR` | Philibert `NOT_LISTED` **and** no FR edition exists | 40 |
| `UNAVAILABLE_FR?` | Philibert `NOT_LISTED` but FR edition exists (weaker) | 28 + `NEEDS_EYEBALL` |
| `OUT_OF_STOCK_FR` | `LISTED_OUT_OF_STOCK` | 30 |
| `CHEAPER_UK` | in stock both sides & `discount ≥ 40%` | 15 + `min(10, (discount−40)/4)` |
| `NONE` | in stock both sides, discount < 40% | **excluded from shortlist** |

`discount% = (price_eur − price_gbp × FX) / price_eur`, **FX fixed at run-time** (set once in config).
Also requires **Zatu in stock** — an out-of-stock UK game is not an opportunity.

Price is deliberately the *weakest* advantage (max 25 vs 40), per "price is not a strong criteria."

### 5.3 Genre bonus (criterion 3)
`coop +12` · `party +12` · both stackable (+24).

Calibration check, per "an amazing game being neither can also get selected": a 8.6-rated non-coop
game scores 45 quality vs a 7.8-rated coop game's ~19+12=31 — the amazing game wins on merit, while
between two similar-quality games the coop/party one wins comfortably.

### 5.4 Language dependence (criterion 4) — bonus/penalty, not a filter
`LOW (1–2) +10` · `MED (3) 0` · `HIGH (4–5) −15` · `UNKNOWN −3` (mild caution, flagged in UI).

Weighted slightly stronger on the penalty side since heavy-text games are the ones that actually fail
with non-English-speaking players.

---

## 6. Output — static HTML (option a)

Single self-contained file, no server. Contents:

- **One full sortable/filterable table, every game that passed the quality gate and has a genuine UK
  advantage** — no truncation. Columns: score, advantage, quality label, shrunk & raw rating, votes,
  coop/party, language level, GBP, EUR, discount %, match confidence, flags. Default sort is by score
  descending, so the strongest candidates naturally lead — but nothing past some fixed row count is
  hidden. A result count at the top (*"47 games matched your criteria"*) tells you at a glance how much
  there is to look through, so you can decide how far down to go.
- Each row gets a one-line "why", e.g. *"Not sold in France, no FR edition exists · 8.2 (3,400 votes) ·
  coop · low text."*
- **Colour coding** by advantage type; **flag badges** for `NEEDS_EYEBALL`, `UNKNOWN_LANG`, `PREORDER`,
  `VARIANT_EDITION`.
- **Three links per row**: BGG · Zatu · Philibert (or the search URL that found nothing) — so any row
  can be verified in ~5 seconds.
- Sidecar files: `results.csv`, `dropped.csv`, `run_metadata.json` (FX rate, timestamps, counts per stage).

---

## 7. Tech & effort

- **Python.** `requests` + `lxml`/BeautifulSoup; `rapidfuzz` (matching); `pandas`; Jinja2 template with
  DataTables/Alpine for the sortable table. Local **SQLite cache** keyed by source+id, so re-runs are
  incremental and a crashed run resumes.
- **Structure:** `sources/zatu.py`, `sources/philibert.py`, `sources/bgg.py` behind a common adapter
  interface, so a site layout change is an isolated fix. `match.py`, `score.py`, `render.py`.
- **Effort:** ~2–3 days total. Stage 0–2 + scoring on cached data is ~1 day and already produces a
  usable ranked list; Stages 4–5 (the scrapers) are the bulk of the remaining time and the main risk.
- **Runtime:** dominated by polite rate-limiting on Stages 4–5 — expect a long single run (tens of
  minutes to a couple of hours); design it to be resumable and run it once, overnight if needed.

---

## 8. Risks & caveats

- **BGG token approval latency is now the top schedule risk**, not a technical one — register the
  application *today* (§0.1/§0.4); a week-plus turnaround means this can't be done the night before coding.
- **Zatu currency/locale** (§0.2) is the top *correctness* risk — if GBP isn't forced correctly, every
  `CHEAPER_UK` discount computation in §5.2 is silently wrong. Verify and spot-check against a manual
  browser check on a couple of known products before trusting the pipeline's numbers.
- **Philibert scraper fragility / bot protection** (Cloudflare etc.) remains a risk since it still needs
  page fetches (§0.3) — no bulk export exists for this one. Adapter isolation + caching limits the blast
  radius if it breaks mid-run.
- **Online stock ≠ in-store stock.** You'll be near the physical store, but scraped availability is the
  website's. Treat output as a shortlist to verify on arrival, not a guarantee — and consider phoning
  ahead for the 1–3 finalists.
- **Philibert as sole FR proxy** — mitigated but not eliminated by the BGG FR-edition cross-check. A game
  absent from Philibert may still be orderable elsewhere in France.
- **Customs:** goods above **€430 per traveller (air/sea)** entering the EU can attract import VAT/duty on
  the *full* value, which would erase a UK discount. With 0–3 games this is unlikely to bite, but a
  big-box purchase or two could approach it — worth a glance before buying.
- **Politeness/legality:** personal, one-off, low-volume use; respect `robots.txt`, rate-limit, identify
  the client honestly, and don't redistribute scraped data.

---

## 9. Build order (validate the risky dependency first)

0. **Today, before any code:** register the BGG application (§0.1) and start the approval clock;
   manually download `bg_ranks.csv` while you're logged in anyway.
1. Zatu JSON harvest (§0.2, Stage 0) + light filter → count real candidate volume; confirm currency behaviour.
2. Offline matching + quality gate + scoring against the pre-downloaded CSV → first ranked list from
   BGG data alone, no live BGG calls yet. **At this point the tool is already useful**, ranked on
   quality/genre/language, missing only France comparison and confirmed UK price/stock.
3. BGG enrich (Stage 3) — **build this as best-effort, decoupled from the rest** (§0.1): try the token
   first if it's arrived; if not, use BGG's public game-page HTML as a fallback adapter; if neither is
   ready yet, skip and let the pipeline run without coop/party/language signals rather than blocking.
4. Philibert adapter — EAN search first, title fallback (§0.3); availability is the highest-value signal.
5. Confirm Zatu detail fields are complete from Stage 0's JSON; fill gaps per-product only where needed.
6. HTML render + flags.
7. Run, review however many rows actually pass (§6 — no fixed cutoff), pick 0–3.

---

## 10. Config (single file, edit before run)

```yaml
fx_gbp_eur: 1.17            # fixed for the run
discount_threshold: 0.40
quality:
  shrink_M: 100
  prior: 6.5
  min_shrunk: 7.2
  min_votes: 30
weights:
  advantage: {unavailable_fr: 40, unavailable_fr_weak: 28, out_of_stock_fr: 30, cheaper_uk_base: 15}
  genre: {coop: 12, party: 12}
  language: {low: 10, med: 0, high: -15, unknown: -3}
include_expansions: false
rate_limit_sec:
  bgg: 5.0        # BGG's documented courtesy limit — do not lower
  zatu: 1.0
  philibert: 1.0
bgg_bearer_token: ""   # from boardgamegeek.com/applications — required for Stage 3, not Stage 2
```

All tunable knobs live here so re-scoring never requires touching code — and never requires re-scraping,
since scoring runs off the cache.

---

## 11. Appendix — fixtures for coding without live access

Everything below was either **observed directly** on the live sites in this session (marked *real*) or
is the **documented, stable schema** for the platform each site runs on (marked *representative* — field
names and shapes are accurate; specific values are illustrative). Use these to write and sanity-test
parsing code before you have a connection to check against the real thing.

### 11.1 Zatu — real observations worth coding against directly

From a live product page fetch (`/en-us/products/manipulate`), confirmed:

- **The currency bug is real, not hypothetical:** the page's own metadata returned
  `meta-og:price:currency: USD` on an unforced request — for a UK retailer. Don't trust price without
  forcing locale first; whatever you build, add an assertion that checks the currency actually came
  back as GBP before using a price, so a silent locale failure fails loudly instead of corrupting scores.
- **Stock-status strings actually used in the UI** (map these to your `in_stock` boolean/enum):
  `"3+ in stock"`, `"Back-Order"`, `"Out of stock"`, and for pre-orders, phrasing like
  `"Order in next $$ for Next Day Delivery"`.
- **The visible "SKU" is Zatu's internal code, not an EAN** — e.g. `SKU: ZWV-MANIPULATE`. Don't confuse
  this with the `barcode` field on Shopify variants (§0.2); they're different fields and only the latter
  is likely to be a real EAN. Check for `barcode` specifically, and don't fall back to SKU as a substitute.
- Confirmed real board-game product URLs for testing: `/en-us/products/manipulate`,
  `/en-us/products/gloomhaven-jaws-of-the-lion`, `/en-us/products/sea-salt-and-paper`,
  `/en-us/products/the-mind`, `/en-us/products/brass-birmingham`.

**Representative** `products.json` entry shape (standard Shopify storefront schema — confirmed this
store runs Shopify; exact response not captured this session, so treat field presence as likely rather
than guaranteed until you can check live):

```json
{
  "products": [
    {
      "id": 1234567890,
      "title": "Manipulate",
      "handle": "manipulate",
      "product_type": "Board Games",
      "tags": ["Cooperative Play", "Party Games"],
      "variants": [
        {
          "id": 987654321,
          "sku": "ZWV-MANIPULATE",
          "barcode": "5060453690123",
          "price": "19.99",
          "compare_at_price": "29.99",
          "available": true,
          "inventory_quantity": 3
        }
      ],
      "images": [{"src": "https://zatu.com/cdn/shop/files/ZWV-MANIPULATE.jpg"}]
    }
  ]
}
```

Notes for coding: `price`/`compare_at_price` are strings, not numbers — cast explicitly. `available`
is the reliable stock boolean; don't parse it out of display text if the JSON is reachable.
`tags` is a plausible (not confirmed) place mechanics/genre hints might live — treat as a bonus signal,
not a substitute for BGG's own mechanic/category data in Stage 3.

**Verified 2026-08-10, first real harvest (4178 products) via GitHub Actions:** two assumptions above
don't hold on the live store. `barcode` is `null` on **every single variant** across the whole
catalogue — Zatu's public `/collections/.../products.json` never populates it, not even sometimes.
So the EAN-match HIGH-confidence tier in §4.2 has no data to work with from this endpoint; Stage 2
matching will have to run on title (+ year if available) as the primary key, not EAN. Separately,
`inventory_quantity` is also `null` on every variant, and `available` is `true` for all 4178
products — with no inventory number to cross-check against, `available` can't be trusted as a real
stock signal here, contrary to "the reliable stock boolean" above. Real per-product availability, if
it's needed with confidence, will have to come from Stage 4's per-product page fetch (the stock-status
strings in §11.1's confirmed list — `"3+ in stock"`, `"Back-Order"`, `"Out of stock"`, etc.) rather
than the bulk JSON — likely for most products, not just the "minority" Stage 4 originally assumed.
Price itself is solid: spot-checked against a manual browser price (Spirit Island Core Game, £67) and
matched exactly using the bare-path fix above.

`tags` did turn out useful as a bonus signal, still not a substitute for BGG: `"cooperat"`/`"party"`
case-insensitive substring matches hit 338/286 of the 4178 harvested products respectively.
`product_type` is a clean field for light Stage 1 filtering — the harvest split as `Board Games`:
4069, `Accessories`: 81, `Miniatures`: 11, `Books`: 10, `Puzzles`: 6, `Trading Card Games`: 1;
`product_type == "Accessories"` is now an unambiguous drop (`filters.py`), the others are left for
Stage 2 to gate since dropping them at Stage 1 would be a pure recall risk.

**Confirmed 2026-08-10 via `scripts/probe_zatu_detail.py` on GitHub Actions:** the per-product JSON
endpoint (`https://zatu.com/products/<handle>.json`, singular `product` key — standard Shopify
shape) does carry a populated `barcode`, on the same products the bulk `/collections/.../products.json`
returns `null`/nothing for. Sampled three products directly: Manipulate → `5060629590004`
(EAN-13), Spirit Island (Core Game) → `798304339291` (12-digit UPC-A, zero-pads to
`0798304339291`), Brass: Birmingham → `9781988884042` (EAN-13) — all `null` in the same day's bulk
harvest. Each also carried `price_currency: "GBP"`. This is a meaningfully better EAN source than
the bulk endpoint, and makes the EAN-match HIGH-confidence tier in §4.2 viable after all — just not
from Stage 0's bulk harvest; it needs Stage 4's per-product fetch, one request per Stage-2 survivor,
not the whole catalogue. `sources/zatu.py`'s `fetch_product_detail`/`fetch_product_ean` do this (EAN
normalized to EAN-13 via zero-pad for UPC-A, matching Philibert's 13-digit field), and
`verify_gbp_currency` now tries `price_currency` first before falling back to the proven
`og:price:currency` meta-tag check.

### 11.2 BGG — representative `thing` response (schema per official docs, §0.1)

```xml
<items>
  <item type="boardgame" id="174430">
    <name type="primary" value="Gloomhaven" />
    <yearpublished value="2017" />
    <statistics>
      <ratings>
        <average value="8.62" />
        <bayesaverage value="8.42" />
        <usersrated value="63000" />
      </ratings>
    </statistics>
    <link type="boardgamemechanic" id="2023" value="Cooperative Game" />
    <link type="boardgamecategory" id="1022" value="Adventure" />
    <poll name="language_dependence" title="Language Dependence" totalvotes="450">
      <results>
        <result level="1" value="No necessary in-game text" numvotes="20" />
        <result level="2" value="Some necessary text - easily memorized or small crib sheet" numvotes="80" />
        <result level="3" value="Moderate in-game text - needs crib sheet or paste ups" numvotes="250" />
        <result level="4" value="Extensive use of text - massive conversion needed to be playable" numvotes="90" />
        <result level="5" value="Unplayable in another language" numvotes="10" />
      </results>
    </poll>
    <versions>
      <item type="boardgameversion" id="500001">
        <name type="primary" value="French edition" />
        <link type="language" id="2184" value="French" />
      </item>
    </versions>
  </item>
</items>
```

Coding notes: `poll/results/result` gives raw vote counts per level, not a pre-computed winner — you sum
or take plurality yourself (§3, Stage 3). A request without a valid `Authorization: Bearer` header should
be expected to fail (401/403) per §0.1 — write the auth-failure path deliberately rather than discovering
it live. A cold cache miss can return **HTTP 202** with an empty/placeholder body — code the retry loop
before your first real run, not after it silently returns nothing. **Field names/shapes above are from
BGG's own documentation and are trustworthy; the response was not captured live this session** (the
endpoint isn't reachable via search), so the exact error format for an unauthenticated request is the one
genuinely untested piece — confirm it on your first real call rather than assuming.

### 11.3 Philibert — real captured product page (not representative — this is the actual data)

Live fetch of `/fr/iello/171597-athletes-de-compete-3701551706461.html`:

```
Français · à partir de 6 ans · moins de 30mn · 2 à 6 joueurs
Précommande : Fin aout/début septembre
26,90€

Fiche technique
  Langue(s)     Français
  EAN           3701551706461
  Editeur       Iello
Référence : IEL-70646
```

Parsing notes: extract from the **"Fiche technique" block specifically** — it's the authoritative,
labeled source for `EAN`, `Langue(s)`, and publisher, more robust than regexing the URL or scraping
loose page text. Availability for this example was a pre-order (`Précommande`/`Précommander` button);
the exact string for a **sold-out primary product** wasn't observed this session — confirm on a real
out-of-stock item once you have connectivity, since it's the one stock-related string still unconfirmed.
Ignore any `product.oos`/`product.declinaisons` text you see — those are unrendered template keys that
leak on the small cross-sell cards ("Produits associés", "Accessoires"), not real data, and not present
in the main product's own block.

Other real product URLs confirmed live, showing the EAN-in-URL pattern (regex `\d{13}(?=\.html$)`):

```
/fr/iello/171597-athletes-de-compete-3701551706461.html
/fr/libellud/173976-harmonies-pulse-3558387002577.html
/fr/cmon/170609-collect--3558380139300.html
/fr/catch-up-games/174887-courtisans-diplomates-confidents-3760273010553.html
/fr/space-cowboys/163102-dewan.html
```

Pattern: `/fr/<publisher-slug>/<internal-id>-<name-slug>-<ean13>.html` — the trailing 13-digit number
before `.html` is the EAN whenever present (not every product has it, e.g. the `dewan.html` example) —
though per above, prefer the labeled `EAN` field in "Fiche technique" as the authoritative source and
use this URL pattern only as a fast pre-filter.

Category root for board games (useful for the HTML-sitemap fallback): `/fr/50-jeux-de-societe`.
