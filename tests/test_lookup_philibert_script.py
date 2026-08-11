import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import lookup_philibert  # noqa: E402

SURVIVOR_LISTED_CHEAPER = {
    "zatu_handle": "cheap-in-uk",
    "zatu_title": "Cheap In UK",
    "zatu_ean": "1111111111111",
    "zatu_price_gbp": 20.0,
    "zatu_in_stock": True,
}
SURVIVOR_SIMILAR_PRICE = {
    "zatu_handle": "similar-price",
    "zatu_title": "Similar Price Game",
    "zatu_ean": "2222222222222",
    "zatu_price_gbp": 45.0,
    "zatu_in_stock": True,
}
SURVIVOR_NOT_LISTED = {
    "zatu_handle": "not-listed",
    "zatu_title": "Not Listed Game",
    "zatu_ean": None,
    "zatu_price_gbp": 30.0,
    "zatu_in_stock": True,
}
SURVIVOR_UK_OUT_OF_STOCK = {
    "zatu_handle": "uk-oos",
    "zatu_title": "UK Out Of Stock Game",
    "zatu_ean": "3333333333333",
    "zatu_price_gbp": 25.0,
    "zatu_in_stock": False,
}

TEST_CONFIG = {
    "fx_gbp_eur": 1.0,
    "discount_threshold": 0.40,
    "weights": {
        "advantage": {
            "unavailable_fr": 40,
            "unavailable_fr_weak": 28,
            "out_of_stock_fr": 30,
            "cheaper_uk_base": 15,
        }
    },
    "rate_limit_sec": {"philibert": 0},
}


SURVIVOR_FAMILY_LISTED = {
    "zatu_handle": "complete-collection",
    "zatu_title": "Some Game Complete Collection",
    "zatu_ean": None,
    "zatu_price_gbp": 60.0,
    "zatu_in_stock": True,
}


def fake_lookup_one(session, survivor, rate_limit_sec, override_title=None):
    if survivor["zatu_handle"] == "cheap-in-uk":
        return {"status": "LISTED_IN_STOCK", "price_eur": 100.0, "language": "Français", "url": "u1"}
    if survivor["zatu_handle"] == "similar-price":
        return {"status": "LISTED_IN_STOCK", "price_eur": 50.0, "language": "Français", "url": "u2"}
    if survivor["zatu_handle"] == "uk-oos":
        return {"status": "LISTED_IN_STOCK", "price_eur": 50.0, "language": "Français", "url": "u3"}
    if survivor["zatu_handle"] == "complete-collection":
        return {"status": "FAMILY_LISTED_FR", "price_eur": 45.0, "language": "Français", "url": "u4"}
    return {"status": "NOT_LISTED", "price_eur": None, "language": None, "url": None}


def test_lookup_one_uses_family_fallback_when_exact_title_not_listed(monkeypatch):
    # Real lookup_one() (not the fake), with search_by_ean/search_by_title/search_family_title
    # patched directly, confirms the wiring: exact EAN and title search both fail, family
    # fallback finds a base-game listing -> status FAMILY_LISTED_FR, not NOT_LISTED.
    import lookup_philibert as mod

    monkeypatch.setattr(mod, "search_by_ean", lambda session, ean: None)
    monkeypatch.setattr(mod, "search_by_title", lambda session, title, **kw: None)
    monkeypatch.setattr(mod, "search_family_title", lambda session, title, **kw: "https://www.philibertnet.com/fr/pub/1-base-game.html")
    monkeypatch.setattr(
        mod,
        "fetch_product_page",
        lambda session, url: {
            "ean": None,
            "language": "Français",
            "publisher": "Pub",
            "price_eur": 45.0,
            "stock_status": "IN_STOCK",
        },
    )

    result = mod.lookup_one(session=None, survivor=SURVIVOR_FAMILY_LISTED, rate_limit_sec=0)

    assert result["status"] == "FAMILY_LISTED_FR"
    assert result["url"] == "https://www.philibertnet.com/fr/pub/1-base-game.html"


def test_lookup_one_tries_override_title_before_the_zatu_title(monkeypatch):
    # Real case that prompted this: "EXIT: The Venice Conspiracy" is sold in France under a
    # genuine translation, "EXIT - Intrigue à Venise" -- no automatic heuristic bridges "Venice"
    # to "Venise" or "Conspiracy" to "Intrigue", so a human-confirmed override title is tried
    # first, before the (doomed) ordinary title search ever runs.
    import lookup_philibert as mod

    calls = []

    def fake_search_by_title(session, title, **kw):
        calls.append(title)
        if title == "EXIT - Intrigue à Venise":
            return "https://www.philibertnet.com/fr/iello/157939-exit-intrigue-a-venise.html"
        return None

    monkeypatch.setattr(mod, "search_by_ean", lambda session, ean: None)
    monkeypatch.setattr(mod, "search_by_title", fake_search_by_title)
    monkeypatch.setattr(mod, "search_family_title", lambda session, title, **kw: None)
    monkeypatch.setattr(
        mod,
        "fetch_product_page",
        lambda session, url: {
            "ean": "3701551704795",
            "language": "Français",
            "publisher": "iello",
            "price_eur": 13.90,
            "stock_status": "IN_STOCK",
        },
    )

    survivor = {
        "zatu_handle": "exit-the-venice-conspiracy",
        "zatu_title": "EXIT: The Venice Conspiracy",
        "zatu_ean": "0810172680012",
        "zatu_price_gbp": 12.45,
        "zatu_in_stock": True,
    }
    result = mod.lookup_one(
        session=None, survivor=survivor, rate_limit_sec=0,
        override_title="EXIT - Intrigue à Venise",
    )

    assert result["status"] == "LISTED_IN_STOCK"
    assert result["url"] == "https://www.philibertnet.com/fr/iello/157939-exit-intrigue-a-venise.html"
    # the override was tried before the real zatu_title -- confirmed by call order, not just
    # the end result, since a title search that happened to match either title would look the
    # same from the result alone
    assert calls[0] == "EXIT - Intrigue à Venise"
    assert "EXIT: The Venice Conspiracy" not in calls  # short-circuited, never even tried


def test_main_wires_title_overrides_through_by_handle(tmp_path, monkeypatch):
    survivor = {
        "zatu_handle": "exit-the-venice-conspiracy",
        "zatu_title": "EXIT: The Venice Conspiracy",
        "zatu_ean": None,
        "zatu_price_gbp": 12.45,
        "zatu_in_stock": True,
    }
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [survivor]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"
    overrides_file = tmp_path / "overrides.json"
    overrides_file.write_text(json.dumps({"exit-the-venice-conspiracy": "EXIT - Intrigue à Venise"}))

    seen_overrides = []

    def fake_lookup_one(session, survivor, rate_limit_sec, override_title=None):
        seen_overrides.append(override_title)
        return {"status": "LISTED_IN_STOCK", "price_eur": 13.90, "language": "Français", "url": "u1"}

    monkeypatch.setattr(lookup_philibert, "lookup_one", fake_lookup_one)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lookup_philibert.py",
            "--matched", str(matched_file),
            "--config", str(config_file),
            "--out", str(out_file),
            "--shortlist-out", str(shortlist_file),
            "--title-overrides", str(overrides_file),
        ],
    )

    exit_code = lookup_philibert.main()

    assert exit_code == 0
    assert seen_overrides == ["EXIT - Intrigue à Venise"]


def test_main_removes_similar_price_games_keeps_cheaper_and_not_listed(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({
        "survivors": [
            SURVIVOR_LISTED_CHEAPER,
            SURVIVOR_SIMILAR_PRICE,
            SURVIVOR_NOT_LISTED,
            SURVIVOR_UK_OUT_OF_STOCK,
            SURVIVOR_FAMILY_LISTED,
        ]
    }))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))

    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    monkeypatch.setattr(lookup_philibert, "lookup_one", fake_lookup_one)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lookup_philibert.py",
            "--matched",
            str(matched_file),
            "--config",
            str(config_file),
            "--out",
            str(out_file),
            "--shortlist-out",
            str(shortlist_file),
        ],
    )

    exit_code = lookup_philibert.main()

    assert exit_code == 0
    results = json.loads(out_file.read_text())["results"]
    shortlist = json.loads(shortlist_file.read_text())["shortlist"]

    by_handle = {r["zatu_handle"]: r for r in results}
    assert by_handle["cheap-in-uk"]["advantage_verdict"] == "CHEAPER_UK"
    assert by_handle["similar-price"]["advantage_verdict"] == "NONE"
    assert by_handle["not-listed"]["advantage_verdict"] == "UNAVAILABLE_FR"
    assert by_handle["uk-oos"]["advantage_verdict"] == "EXCLUDED"
    assert by_handle["complete-collection"]["advantage_verdict"] == "FAMILY_AVAILABLE_FR"

    shortlist_handles = {r["zatu_handle"] for r in shortlist}
    assert shortlist_handles == {"cheap-in-uk", "not-listed"}
    assert "similar-price" not in shortlist_handles  # the actual removal the user asked for
    assert "uk-oos" not in shortlist_handles
    # family-available games aren't a real UK-buy opportunity either -- same treatment as NONE
    assert "complete-collection" not in shortlist_handles


def test_main_survives_a_lookup_error(tmp_path, monkeypatch, capsys):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_LISTED_CHEAPER]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    def flaky_lookup(session, survivor, rate_limit_sec, override_title=None):
        raise RuntimeError("simulated network error")

    monkeypatch.setattr(lookup_philibert, "lookup_one", flaky_lookup)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lookup_philibert.py",
            "--matched",
            str(matched_file),
            "--config",
            str(config_file),
            "--out",
            str(out_file),
            "--shortlist-out",
            str(shortlist_file),
        ],
    )

    exit_code = lookup_philibert.main()

    assert exit_code == 0
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["philibert_status"] == "NOT_LISTED"  # safe fallback, not a crash
    assert "ERROR cheap-in-uk" in capsys.readouterr().err


def _run_main(matched_file, config_file, out_file, shortlist_file, extra_args=None):
    sys.argv = [
        "lookup_philibert.py",
        "--matched", str(matched_file),
        "--config", str(config_file),
        "--out", str(out_file),
        "--shortlist-out", str(shortlist_file),
        *(extra_args or []),
    ]
    return lookup_philibert.main()


def test_main_passes_fr_edition_exists_into_the_advantage_verdict(tmp_path, monkeypatch):
    # Real case that prompted this: Gloomhaven: Jaws of the Lion (bgg_id=291457) is NOT_LISTED
    # on Philibert, but BGG's own versions data confirms a real French edition exists -- the
    # user doesn't want that treated the same as "no French edition anywhere".
    survivor = {**SURVIVOR_NOT_LISTED, "bgg_id": 291457}
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [survivor]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"
    fr_editions_file = tmp_path / "fr_editions.json"
    fr_editions_file.write_text(json.dumps({
        "291457": {"fr_edition_exists": True, "fr_edition_titles": ["Gloomhaven: Aventures a Havrenuit"]},
    }))

    monkeypatch.setattr(
        lookup_philibert, "lookup_one",
        lambda session, survivor, rate_limit_sec, override_title=None: {"status": "NOT_LISTED", "price_eur": None, "language": None, "url": None},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lookup_philibert.py",
            "--matched", str(matched_file),
            "--config", str(config_file),
            "--out", str(out_file),
            "--shortlist-out", str(shortlist_file),
            "--fr-editions", str(fr_editions_file),
        ],
    )

    exit_code = lookup_philibert.main()

    assert exit_code == 0
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["advantage_verdict"] == "FRENCH_EDITION_EXISTS"
    assert "a French edition exists" in results[0]["advantage_reason"]
    assert results[0]["needs_eyeball"] is True
    # excluded from the shortlist -- user's explicit call: a known French edition, even one
    # that's not currently purchasable, means this isn't a genuine UK-exclusive buy
    shortlist = json.loads(shortlist_file.read_text())["shortlist"]
    assert shortlist == []


def test_main_passes_bgg_language_level_through_to_the_record(tmp_path, monkeypatch):
    survivor = {**SURVIVOR_NOT_LISTED, "bgg_id": 174430}
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [survivor]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"
    fr_editions_file = tmp_path / "fr_editions.json"
    fr_editions_file.write_text(json.dumps({
        "174430": {"fr_edition_exists": False, "fr_edition_titles": [], "language_level": "MED", "language_votes": {}},
    }))

    monkeypatch.setattr(
        lookup_philibert, "lookup_one",
        lambda session, survivor, rate_limit_sec, override_title=None: {"status": "NOT_LISTED", "price_eur": None, "language": None, "url": None},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lookup_philibert.py",
            "--matched", str(matched_file),
            "--config", str(config_file),
            "--out", str(out_file),
            "--shortlist-out", str(shortlist_file),
            "--fr-editions", str(fr_editions_file),
        ],
    )

    exit_code = lookup_philibert.main()

    assert exit_code == 0
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["bgg_language_level"] == "MED"


def test_main_bgg_language_level_none_when_not_checked(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_NOT_LISTED]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    monkeypatch.setattr(
        lookup_philibert, "lookup_one",
        lambda session, survivor, rate_limit_sec, override_title=None: {"status": "NOT_LISTED", "price_eur": None, "language": None, "url": None},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lookup_philibert.py",
            "--matched", str(matched_file),
            "--config", str(config_file),
            "--out", str(out_file),
            "--shortlist-out", str(shortlist_file),
        ],
    )

    exit_code = lookup_philibert.main()

    assert exit_code == 0
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["bgg_language_level"] is None


def test_main_reuses_cached_durable_result_without_a_live_lookup(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_LISTED_CHEAPER]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    # Pre-seed a prior run's output with a durable LISTED_IN_STOCK result for this survivor.
    out_file.write_text(json.dumps({"results": [{
        **SURVIVOR_LISTED_CHEAPER,
        "philibert_status": "LISTED_IN_STOCK",
        "philibert_price_eur": 100.0,
        "philibert_language": "Français",
        "philibert_url": "https://www.philibertnet.com/fr/pub/1-cheap.html",
        "philibert_stock_status_raw": "IN_STOCK",
        "advantage_verdict": "CHEAPER_UK",
        "advantage_points": 25.0,
        "discount_pct": 0.8,
        "needs_eyeball": False,
        "advantage_reason": "stale",
    }]}))

    calls = []
    monkeypatch.setattr(
        lookup_philibert, "lookup_one",
        lambda session, survivor, rate_limit_sec, override_title=None: calls.append(survivor["zatu_handle"]) or {},
    )

    exit_code = _run_main(matched_file, config_file, out_file, shortlist_file)

    assert exit_code == 0
    assert calls == []  # no live lookup at all -- reused the cached durable result
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["philibert_status"] == "LISTED_IN_STOCK"
    assert results[0]["philibert_price_eur"] == 100.0
    # advantage is recomputed fresh from current survivor data, not blindly copied from cache
    assert results[0]["advantage_verdict"] == "CHEAPER_UK"
    assert results[0]["advantage_reason"] != "stale"


def test_main_always_rechecks_not_listed_cached_survivors(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_NOT_LISTED]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    out_file.write_text(json.dumps({"results": [{
        **SURVIVOR_NOT_LISTED,
        "philibert_status": "NOT_LISTED",
        "philibert_price_eur": None,
        "philibert_language": None,
        "philibert_url": None,
        "philibert_stock_status_raw": None,
        "advantage_verdict": "UNAVAILABLE_FR",
        "advantage_points": 28,
        "discount_pct": None,
        "needs_eyeball": True,
        "advantage_reason": "stale",
    }]}))

    calls = []

    def tracking_lookup(session, survivor, rate_limit_sec, override_title=None):
        calls.append(survivor["zatu_handle"])
        return {"status": "LISTED_IN_STOCK", "price_eur": 50.0, "language": "Français", "url": "u1"}

    monkeypatch.setattr(lookup_philibert, "lookup_one", tracking_lookup)

    exit_code = _run_main(matched_file, config_file, out_file, shortlist_file)

    assert exit_code == 0
    assert calls == ["not-listed"]  # NOT_LISTED is never trusted from cache -- always re-checked
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["philibert_status"] == "LISTED_IN_STOCK"  # the fresh, corrected result


def test_main_offline_flag_reuses_not_listed_cache_without_a_live_lookup(tmp_path, monkeypatch):
    # For applying an advantage.py/config.yaml change to already-fetched data without a live
    # re-run -- unlike the default cache policy, --offline also trusts a cached NOT_LISTED.
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_NOT_LISTED]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    out_file.write_text(json.dumps({"results": [{
        **SURVIVOR_NOT_LISTED,
        "philibert_status": "NOT_LISTED",
        "philibert_price_eur": None,
        "philibert_language": None,
        "philibert_url": None,
        "philibert_stock_status_raw": None,
        "advantage_verdict": "UNAVAILABLE_FR",
        "advantage_points": 28,
        "discount_pct": None,
        "needs_eyeball": True,
        "advantage_reason": "stale",
    }]}))

    calls = []
    monkeypatch.setattr(
        lookup_philibert, "lookup_one",
        lambda session, survivor, rate_limit_sec, override_title=None: calls.append(survivor["zatu_handle"]) or {},
    )

    exit_code = _run_main(matched_file, config_file, out_file, shortlist_file, extra_args=["--offline"])

    assert exit_code == 0
    assert calls == []  # no live lookup at all, even though the cached status is NOT_LISTED
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["philibert_status"] == "NOT_LISTED"


def test_main_offline_and_refresh_are_mutually_exclusive(tmp_path, monkeypatch, capsys):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": []}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    monkeypatch.setattr(
        sys, "argv",
        [
            "lookup_philibert.py",
            "--matched", str(matched_file),
            "--config", str(config_file),
            "--out", str(out_file),
            "--shortlist-out", str(shortlist_file),
            "--offline", "--refresh",
        ],
    )

    try:
        lookup_philibert.main()
        assert False, "expected SystemExit from argparse.error"
    except SystemExit as exc:
        assert exc.code == 2


def test_main_refresh_flag_ignores_cache_entirely(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_LISTED_CHEAPER]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    out_file.write_text(json.dumps({"results": [{
        **SURVIVOR_LISTED_CHEAPER,
        "philibert_status": "LISTED_IN_STOCK",
        "philibert_price_eur": 100.0,
        "philibert_language": "Français",
        "philibert_url": "https://www.philibertnet.com/fr/pub/1-cheap.html",
        "philibert_stock_status_raw": "IN_STOCK",
        "advantage_verdict": "CHEAPER_UK",
        "advantage_points": 25.0,
        "discount_pct": 0.8,
        "needs_eyeball": False,
        "advantage_reason": "stale",
    }]}))

    calls = []

    def tracking_lookup(session, survivor, rate_limit_sec, override_title=None):
        calls.append(survivor["zatu_handle"])
        return {"status": "LISTED_IN_STOCK", "price_eur": 999.0, "language": "Français", "url": "u2"}

    monkeypatch.setattr(lookup_philibert, "lookup_one", tracking_lookup)

    exit_code = _run_main(matched_file, config_file, out_file, shortlist_file, extra_args=["--refresh"])

    assert exit_code == 0
    assert calls == ["cheap-in-uk"]  # --refresh forces a live lookup despite the durable cache
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["philibert_price_eur"] == 999.0
