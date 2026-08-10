import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import harvest_zatu  # noqa: E402

from sources.zatu import ZatuProduct, ZatuVariant  # noqa: E402

SAMPLE_PRODUCTS = [
    ZatuProduct(
        zatu_id=1,
        handle="manipulate",
        title="Manipulate",
        url="https://zatu.com/products/manipulate",
        product_type="Board Games",
        vendor="Zatu Games",
        tags=["Party Games"],
        variants=[
            ZatuVariant(
                variant_id=1,
                title="Default Title",
                sku="ZWV-MANIPULATE",
                barcode="5060453690123",
                price_gbp=19.99,
                compare_at_price_gbp=29.99,
                available=True,
                inventory_quantity=3,
            )
        ],
    )
]


def test_main_aborts_when_currency_check_fails(tmp_path, monkeypatch):
    out_file = tmp_path / "out.json"
    monkeypatch.setattr(harvest_zatu, "verify_gbp_currency", lambda session: False)
    monkeypatch.setattr(sys, "argv", ["harvest_zatu.py", "--out", str(out_file)])

    exit_code = harvest_zatu.main()

    assert exit_code == 1
    assert not out_file.exists()


def test_main_writes_expected_json(tmp_path, monkeypatch):
    out_file = tmp_path / "out.json"
    monkeypatch.setattr(harvest_zatu, "verify_gbp_currency", lambda session: True)
    monkeypatch.setattr(harvest_zatu, "harvest_all", lambda **kwargs: SAMPLE_PRODUCTS)
    monkeypatch.setattr(sys, "argv", ["harvest_zatu.py", "--out", str(out_file)])

    exit_code = harvest_zatu.main()

    assert exit_code == 0
    payload = json.loads(out_file.read_text())
    assert payload["run_metadata"]["currency_verified"] is True
    assert payload["run_metadata"]["kept_count"] == 1
    product = payload["products"][0]
    assert product["handle"] == "manipulate"
    assert product["variants"][0]["barcode"] == "5060453690123"
    # Computed properties (ean/in_stock/min_price_gbp) must survive serialization —
    # dataclasses.asdict() silently drops @property methods, so this is worth pinning.
    assert product["ean"] == "5060453690123"
    assert product["in_stock"] is True
    assert product["min_price_gbp"] == 19.99


def test_skip_currency_check_flag_bypasses_verification(tmp_path, monkeypatch):
    out_file = tmp_path / "out.json"

    def fail_if_called(session):
        raise AssertionError("verify_gbp_currency should not be called with --skip-currency-check")

    monkeypatch.setattr(harvest_zatu, "verify_gbp_currency", fail_if_called)
    monkeypatch.setattr(harvest_zatu, "harvest_all", lambda **kwargs: SAMPLE_PRODUCTS)
    monkeypatch.setattr(
        sys, "argv", ["harvest_zatu.py", "--out", str(out_file), "--skip-currency-check"]
    )

    exit_code = harvest_zatu.main()

    assert exit_code == 0
    payload = json.loads(out_file.read_text())
    assert payload["run_metadata"]["currency_verified"] is False
