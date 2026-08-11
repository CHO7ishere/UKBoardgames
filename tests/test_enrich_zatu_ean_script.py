import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import enrich_zatu_ean  # noqa: E402

SAMPLE_PAYLOAD = {
    "survivors": [
        {"zatu_handle": "manipulate", "zatu_title": "Manipulate", "zatu_ean": None},
        {"zatu_handle": "brass-birmingham", "zatu_title": "Brass: Birmingham", "zatu_ean": None},
    ]
}

FAKE_EANS = {
    "manipulate": "5060629590004",
    "brass-birmingham": None,  # simulate a lookup that finds nothing
}


def test_main_populates_real_eans(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps(SAMPLE_PAYLOAD))
    out_file = tmp_path / "out.json"

    monkeypatch.setattr(
        enrich_zatu_ean, "fetch_product_ean", lambda session, handle: FAKE_EANS[handle]
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_zatu_ean.py",
            "--matched",
            str(matched_file),
            "--out",
            str(out_file),
            "--rate-limit-sec",
            "0",
        ],
    )

    exit_code = enrich_zatu_ean.main()

    assert exit_code == 0
    payload = json.loads(out_file.read_text())
    by_handle = {s["zatu_handle"]: s for s in payload["survivors"]}
    assert by_handle["manipulate"]["zatu_ean"] == "5060629590004"
    assert by_handle["brass-birmingham"]["zatu_ean"] is None


def test_main_skips_survivors_with_an_already_cached_ean(tmp_path, monkeypatch):
    payload = {
        "survivors": [
            {"zatu_handle": "manipulate", "zatu_title": "Manipulate", "zatu_ean": "5060629590004"},
            {"zatu_handle": "brass-birmingham", "zatu_title": "Brass: Birmingham", "zatu_ean": None},
        ]
    }
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps(payload))
    out_file = tmp_path / "out.json"

    calls = []

    def tracking_fetch(session, handle):
        calls.append(handle)
        return "9781988884042"

    monkeypatch.setattr(enrich_zatu_ean, "fetch_product_ean", tracking_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["enrich_zatu_ean.py", "--matched", str(matched_file), "--out", str(out_file), "--rate-limit-sec", "0"],
    )

    exit_code = enrich_zatu_ean.main()

    assert exit_code == 0
    # only the uncached survivor triggers a live fetch -- the already-cached one is skipped
    assert calls == ["brass-birmingham"]
    by_handle = {s["zatu_handle"]: s for s in json.loads(out_file.read_text())["survivors"]}
    assert by_handle["manipulate"]["zatu_ean"] == "5060629590004"  # untouched, kept the cached value
    assert by_handle["brass-birmingham"]["zatu_ean"] == "9781988884042"


def test_main_refresh_flag_refetches_even_cached_survivors(tmp_path, monkeypatch):
    payload = {
        "survivors": [
            {"zatu_handle": "manipulate", "zatu_title": "Manipulate", "zatu_ean": "5060629590004"},
        ]
    }
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps(payload))
    out_file = tmp_path / "out.json"

    calls = []

    def tracking_fetch(session, handle):
        calls.append(handle)
        return "0000000000000"

    monkeypatch.setattr(enrich_zatu_ean, "fetch_product_ean", tracking_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["enrich_zatu_ean.py", "--matched", str(matched_file), "--out", str(out_file), "--rate-limit-sec", "0", "--refresh"],
    )

    exit_code = enrich_zatu_ean.main()

    assert exit_code == 0
    assert calls == ["manipulate"]  # --refresh forces the fetch even though it was already cached
    by_handle = {s["zatu_handle"]: s for s in json.loads(out_file.read_text())["survivors"]}
    assert by_handle["manipulate"]["zatu_ean"] == "0000000000000"


def test_main_survives_a_lookup_error(tmp_path, monkeypatch, capsys):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps(SAMPLE_PAYLOAD))
    out_file = tmp_path / "out.json"

    def flaky_fetch(session, handle):
        if handle == "manipulate":
            raise RuntimeError("simulated network error")
        return "9781988884042"

    monkeypatch.setattr(enrich_zatu_ean, "fetch_product_ean", flaky_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_zatu_ean.py",
            "--matched",
            str(matched_file),
            "--out",
            str(out_file),
            "--rate-limit-sec",
            "0",
        ],
    )

    exit_code = enrich_zatu_ean.main()

    assert exit_code == 0  # one bad product must not kill the run
    payload = json.loads(out_file.read_text())
    by_handle = {s["zatu_handle"]: s for s in payload["survivors"]}
    assert by_handle["manipulate"]["zatu_ean"] is None
    assert by_handle["brass-birmingham"]["zatu_ean"] == "9781988884042"
    assert "ERROR manipulate" in capsys.readouterr().err
