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
