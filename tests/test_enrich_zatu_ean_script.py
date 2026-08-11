import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import enrich_zatu_ean  # noqa: E402

SAMPLE_PAYLOAD = {
    "survivors": [
        {"zatu_handle": "manipulate", "zatu_title": "Manipulate", "zatu_ean": None, "zatu_image_url": None},
        {"zatu_handle": "brass-birmingham", "zatu_title": "Brass: Birmingham", "zatu_ean": None, "zatu_image_url": None},
    ]
}

FAKE_DETAILS = {
    "manipulate": {
        "variants": [{"barcode": "5060629590004"}],
        "image": {"src": "https://cdn.zatu.example/manipulate.jpg"},
    },
    "brass-birmingham": {
        "variants": [{"barcode": None}],  # simulate a lookup that finds nothing
        "image": None,
    },
}


def _fake_fetch_product_detail(session, handle):
    return FAKE_DETAILS[handle]


def test_main_populates_real_eans_and_images(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps(SAMPLE_PAYLOAD))
    out_file = tmp_path / "out.json"

    monkeypatch.setattr(enrich_zatu_ean, "fetch_product_detail", _fake_fetch_product_detail)
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
    assert by_handle["manipulate"]["zatu_image_url"] == "https://cdn.zatu.example/manipulate.jpg"
    assert by_handle["brass-birmingham"]["zatu_ean"] is None
    assert by_handle["brass-birmingham"]["zatu_image_url"] is None


def test_main_skips_survivors_with_both_already_cached(tmp_path, monkeypatch):
    payload = {
        "survivors": [
            {
                "zatu_handle": "manipulate",
                "zatu_title": "Manipulate",
                "zatu_ean": "5060629590004",
                "zatu_image_url": "https://cdn.zatu.example/manipulate.jpg",
            },
            {"zatu_handle": "brass-birmingham", "zatu_title": "Brass: Birmingham", "zatu_ean": None, "zatu_image_url": None},
        ]
    }
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps(payload))
    out_file = tmp_path / "out.json"

    calls = []

    def tracking_fetch(session, handle):
        calls.append(handle)
        return {"variants": [{"barcode": "9781988884042"}], "image": {"src": "https://cdn.zatu.example/brass.jpg"}}

    monkeypatch.setattr(enrich_zatu_ean, "fetch_product_detail", tracking_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["enrich_zatu_ean.py", "--matched", str(matched_file), "--out", str(out_file), "--rate-limit-sec", "0"],
    )

    exit_code = enrich_zatu_ean.main()

    assert exit_code == 0
    # only the not-fully-cached survivor triggers a live fetch -- the already-cached one is skipped
    assert calls == ["brass-birmingham"]
    by_handle = {s["zatu_handle"]: s for s in json.loads(out_file.read_text())["survivors"]}
    assert by_handle["manipulate"]["zatu_ean"] == "5060629590004"  # untouched, kept the cached value
    assert by_handle["brass-birmingham"]["zatu_ean"] == "9781988884042"
    assert by_handle["brass-birmingham"]["zatu_image_url"] == "https://cdn.zatu.example/brass.jpg"


def test_main_refresh_flag_refetches_even_cached_survivors(tmp_path, monkeypatch):
    payload = {
        "survivors": [
            {
                "zatu_handle": "manipulate",
                "zatu_title": "Manipulate",
                "zatu_ean": "5060629590004",
                "zatu_image_url": "https://cdn.zatu.example/manipulate.jpg",
            },
        ]
    }
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps(payload))
    out_file = tmp_path / "out.json"

    calls = []

    def tracking_fetch(session, handle):
        calls.append(handle)
        return {"variants": [{"barcode": "0000000000000"}], "image": {"src": "https://cdn.zatu.example/new.jpg"}}

    monkeypatch.setattr(enrich_zatu_ean, "fetch_product_detail", tracking_fetch)
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
    assert by_handle["manipulate"]["zatu_image_url"] == "https://cdn.zatu.example/new.jpg"


def test_main_survives_a_lookup_error(tmp_path, monkeypatch, capsys):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps(SAMPLE_PAYLOAD))
    out_file = tmp_path / "out.json"

    def flaky_fetch(session, handle):
        if handle == "manipulate":
            raise RuntimeError("simulated network error")
        return {"variants": [{"barcode": "9781988884042"}], "image": {"src": "https://cdn.zatu.example/brass.jpg"}}

    monkeypatch.setattr(enrich_zatu_ean, "fetch_product_detail", flaky_fetch)
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
    assert by_handle["manipulate"]["zatu_image_url"] is None
    assert by_handle["brass-birmingham"]["zatu_ean"] == "9781988884042"
    assert "ERROR manipulate" in capsys.readouterr().err
