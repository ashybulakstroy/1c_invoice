"""Synthetic contract tests for the receipt → invoice adapter (Etap 1).

No real photos, no OCR: pure dict fixtures shaped like the snapshot that
`App.web_pipeline` / `App.receipt_editing` materialize into `receipt.json`.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from App.invoicing.receipt_adapter import (
    ReceiptSnapshot,
    snapshot_from_directory,
    snapshot_from_receipt,
    to_generation_source,
)


def registry_row(row, kind, name, quantity, price, line_total=None, *, name_raw=None,
                 article="", catalog_key="", origin="ocr", confirmed=False,
                 invalid_fields=None, needs_review=False, reason=None):
    return {
        "row": row,
        "kind": kind,
        "name": name,
        "name_raw": name_raw if name_raw is not None else name,
        "article": article,
        "catalog_key": catalog_key,
        "quantity": quantity,
        "price": price,
        "quantity_raw": quantity,
        "price_raw": price,
        "line_total": line_total,
        "name_origin": origin,
        "name_confirmed": confirmed,
        "invalid_fields": invalid_fields or [],
        "needs_review": needs_review,
        "review_reason": reason,
    }


def full_receipt(**overrides):
    receipt = {
        "job_id": "a" * 32,
        "revision": 3,
        "filename": "IMG_0001.jpeg",
        "date": "16.10.2026",
        "order_number": "1234567890",
        "expected_total": "2250.00",
        "expected_total_source": "ocr_total_row",
        "vat_rate_percent": "16",
        "vat_rate_source": "env_file",
        "warnings": ["Предупреждение пайплайна"],
        "rows": [
            {"row": 1, "kind": "header", "name": "МАГАЗИН", "name_raw": "МАГАЗИН"},
            registry_row(2, "product", "Плёнка полиэтиленовая 100 мкм", "1", "1200.00", "1200.00",
                         name_raw="Пленка полиэтилен. 100мк", article="PL100",
                         catalog_key="плёнка полиэтиленовая 100 мкм", origin="catalog"),
            {"row": 3, "kind": "product", "name": "Грунтовка 10 л", "name_raw": "Груновка 10л",
             "article": "", "catalog_key": "", "quantity": "5", "price": "150.00",
             "quantity_raw": "5", "price_raw": "150.00", "line_total": "750.00",
             "name_origin": "ocr", "name_confirmed": True, "invalid_fields": [],
             "needs_review": False, "review_reason": None},
            registry_row(4, "service", "Доставка", "1", "300.00", "300.00"),
            {"row": 5, "kind": "tax", "name": "НДС", "name_raw": "НДС", "quantity": "",
             "price": "2250.00", "quantity_raw": "", "price_raw": "2250.00",
             "line_total": "2250.00", "name_origin": "ocr", "name_confirmed": False,
             "invalid_fields": [], "needs_review": False, "review_reason": None,
             "vat_status": "match"},
            {"row": 6, "kind": "total", "name": "Итого", "name_raw": "Итого", "quantity": "",
             "price": "2250.00"},
        ],
        "calculation": {
            "status": "match",
            "validation_status": "match",
            "vat": {"status": "match", "expected_tax": "16.68", "difference": "0.00",
                    "rate_percent": "16", "rows": []},
            "products_subtotal": "1950.00",
            "services_subtotal": "300.00",
            "tax_subtotal": "2250.00",
            "computed_total": "2250.00",
            "expected_total": "2250.00",
            "difference": "0.00",
            "missing_rows": [],
            "missing_original_total": False,
        },
        "finalized": True,
        "finalized_at": "2026-10-29T09:15:00+00:00",
    }
    receipt.update(overrides)
    return receipt


def test_full_snapshot_excludes_non_payable_and_keeps_payable():
    snapshot = snapshot_from_receipt(full_receipt())
    kinds = [(line.row_id, line.line_kind) for line in snapshot.lines]
    assert kinds == [(2, "product"), (3, "product"), (4, "service")]
    assert snapshot.job_id == "a" * 32
    assert snapshot.revision == 3 and snapshot.finalized is True
    assert snapshot.validation_status == "match"
    assert snapshot.expected_total == Decimal("2250.00")
    assert snapshot.products_subtotal == Decimal("1950.00")
    assert snapshot.services_subtotal == Decimal("300.00")
    assert snapshot.vat.amount == Decimal("2250.00")
    assert snapshot.vat.status == "match"
    assert snapshot.vat.tax_row_ids == [5]
    assert snapshot.date == "16.10.2026" and snapshot.order_number == "1234567890"


def test_confirmed_name_wins_and_ocr_name_stays_evidence():
    snapshot = snapshot_from_receipt(full_receipt())
    film = snapshot.lines[0]
    assert film.name == "Плёнка полиэтиленовая 100 мкм"
    assert film.ocr_name == "Пленка полиэтилен. 100мк"
    assert film.edited_name is True and film.article == "PL100"
    undated = snapshot.lines[1]
    assert undated.edited_name is False and undated.name_confirmed is True
    assert undated.ocr_name == "Груновка 10л"


def test_fingerprint_is_stable_and_revision_sensitive():
    receipt = full_receipt()
    first = snapshot_from_receipt(receipt)
    again = snapshot_from_receipt(full_receipt())
    assert first.fingerprint == again.fingerprint
    assert len(first.fingerprint) == 64
    changed = snapshot_from_receipt(full_receipt(revision=4))
    assert changed.fingerprint != first.fingerprint


def test_invalid_rows_stay_visible():
    receipt = full_receipt()
    broken = registry_row(7, "product", "Без цены чека", "", "", None)
    receipt["rows"].append(broken)
    snapshot = snapshot_from_receipt(receipt)
    victims = [line for line in snapshot.lines if line.row_id == 7]
    assert len(victims) == 1
    assert "quantity" in victims[0].invalid_fields and "price" in victims[0].invalid_fields
    assert victims[0].needs_review is True
    assert any("Строка 7" in warning for warning in snapshot.warnings)


def test_amount_mismatch_is_flagged_not_corrected():
    receipt = full_receipt()
    receipt["rows"][2]["line_total"] = "760.00"
    snapshot = snapshot_from_receipt(receipt)
    line = next(line for line in snapshot.lines if line.row_id == 3)
    assert line.line_amount == Decimal("760.00")
    assert line.quantity * line.price == Decimal("750.00")
    assert any("Строка 3" in warning and "не равно сумме" in warning for warning in snapshot.warnings)


def test_unknown_row_kind_is_excluded_with_warning():
    receipt = full_receipt()
    receipt["rows"].append({"row": 9, "kind": "bump", "name": "??"})
    snapshot = snapshot_from_receipt(receipt)
    assert all(line.row_id != 9 for line in snapshot.lines)
    assert any("неизвестный тип" in warning for warning in snapshot.warnings)


def test_structural_errors():
    with pytest.raises(ValueError):
        snapshot_from_receipt({"job_id": "j", "rows": []})
    no_rows = full_receipt()
    del no_rows["rows"]
    with pytest.raises(ValueError):
        snapshot_from_receipt(no_rows)
    with pytest.raises(ValueError):
        snapshot_from_receipt(full_receipt(job_id=None))
    duplicated = full_receipt()
    duplicated["rows"].append(registry_row(2, "product", "Дубль", "1", "1", "1"))
    with pytest.raises(ValueError):
        snapshot_from_receipt(duplicated)


def test_receipt_without_vat_rows_and_without_printed_total():
    receipt = full_receipt()
    receipt["rows"] = [row for row in receipt["rows"] if row.get("kind") != "tax"]
    receipt["calculation"]["tax_subtotal"] = "0.00"
    receipt["calculation"]["vat"] = {"status": "not_applicable"}
    receipt["calculation"]["expected_total"] = None
    del receipt["expected_total"]
    snapshot = snapshot_from_receipt(receipt)
    assert snapshot.vat.amount is None
    assert snapshot.vat.status == "not_applicable"
    assert snapshot.expected_total is None


def test_receipt_warnings_are_carried_through():
    snapshot = snapshot_from_receipt(full_receipt())
    assert "Предупреждение пайплайна" in snapshot.warnings


def test_roundtrip_from_directory(tmp_path):
    directory = tmp_path / "web_outputs" / ("b" * 32)
    directory.mkdir(parents=True)
    directory.joinpath("receipt.json").write_text(
        json.dumps(full_receipt(), ensure_ascii=False, indent=2), encoding="utf-8")
    snapshot = snapshot_from_directory(directory)
    assert snapshot == snapshot_from_receipt(full_receipt())


def test_generation_source_matches_donor_contract():
    source = to_generation_source(snapshot_from_receipt(full_receipt()))
    assert source["items"] and len(source["items"]) == 3
    first = source["items"][0]
    for key in ("row_id", "name", "quantity", "price", "amount"):
        assert key in first
    assert first["row_id"] == "2"
    assert first["name"] == "Плёнка полиэтиленовая 100 мкм"
    assert first["edited"] is True
    assert source["vat_amount"] == "2250.00"
    assert source["total"] == "2250.00"
    assert source["date"] == "16.10.2026"
    assert source["order_number"] == "1234567890"
    assert "Предупреждение пайплайна" in source["warnings"]
    assert source["source_job_id"] == "a" * 32 and source["source_revision"] == 3


def test_generation_source_tolerates_real_tenge_strings():
    receipt = full_receipt()
    for payload, raw in (("price", "36530T"), ("quantity", "10 530,00T")):
        receipt["rows"][1][payload] = raw
    receipt["rows"][1]["line_total"] = "36530.00"
    receipt["rows"][1]["quantity_raw"] = receipt["rows"][1]["quantity"]
    receipt["rows"][1]["price_raw"] = receipt["rows"][1]["price"]
    source = to_generation_source(snapshot_from_receipt(receipt))
    first = source["items"][0]
    assert Decimal(first["quantity"]) == Decimal("10530.00")
    assert Decimal(first["price"]) == Decimal("36530")
    assert Decimal(first["amount"]) == Decimal("36530.00")
    # the donor math must survive these values without InvalidOperation
    from App.invoicing import learned_mapping
    applied = learned_mapping.apply_training_pairs(source)
    assert applied["status"] in {"applied", "unmapped"}
