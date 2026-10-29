"""Synthetic + real-boundary tests for learned mapping rules (Etap 3)."""
from __future__ import annotations

import json
from decimal import Decimal

from App.invoicing import learned_mapping as lm


def make_pair(quantity_factor_items=None, *, case_id="case_test", created_at="2026-10-29T10:00:00"):
    """A synthetic two-line receipt → two-line confirmed invoice pair."""
    source_items = quantity_factor_items or [
        {"row_id": "r1", "name": "Профиль потолочный", "ocr_name": "Профиль потолочный",
         "edited": False, "quantity": "2", "price": "100"},
        {"row_id": "r2", "name": "Спрей фиксация", "ocr_name": "Спрей фиксация",
         "edited": False, "quantity": "1", "price": "50"},
    ]
    net = [Decimal(item["quantity"]) * Decimal(item["price"]) for item in source_items]
    net_total = sum(net, Decimal(0))
    vat = Decimal("30")
    total = net_total + vat
    shares = []
    allocated = Decimal(0)
    for index, amount in enumerate(net):
        share = (vat * amount / net_total).quantize(Decimal("0.01"))
        if index == len(net) - 1:
            share = vat - allocated
        allocated += share
        shares.append(amount + share)
    invoice_items = [
        {"row_id": "i1", "name": "Профиль потолочный KNAUF", "unit": "шт",
         "quantity": "4", "amount": str(shares[0])},
        {"row_id": "i2", "name": "Доставка", "unit": "усл",
         "quantity": "1", "amount": str(shares[1])},
    ]
    pair = {
        "case_id": case_id,
        "created_at": created_at,
        "predzakaz": {"items": source_items, "vat_amount": str(vat), "total": str(total), "warnings": []},
        "training_receipt": {"items": source_items, "vat_amount": str(vat), "total": str(total), "warnings": []},
        "invoice": {"items": invoice_items, "vat_amount": str(vat), "total": str(total), "warnings": []},
        "database_id": None,
    }
    return pair


def test_pair_is_learnt_only_when_arithmetic_matches():
    pair = make_pair()
    lm.prepare_training_pair(pair)
    assert pair["training_ready"] is True
    assert pair["status"] == "learned"
    assert [link["source_index"] for link in pair["links"]] == [0, 1]


def test_pair_is_rejected_on_broken_arithmetic():
    pair = make_pair()
    pair["predzakaz"]["total"] = "999999"
    pair["training_receipt"]["total"] = "999999"
    lm.prepare_training_pair(pair)
    assert pair["training_ready"] is False
    assert pair["training_notes"] and any("не сходится" in note for note in pair["training_notes"])


def write_case(training_dir, pair):
    case_dir = training_dir / f"case_{pair['case_id']}"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "expected.json").write_text(json.dumps(pair, ensure_ascii=False, indent=2),
                                            encoding="utf-8")


def test_rules_built_with_factor_and_service(tmp_path):
    training_dir = tmp_path / "training"
    pair = make_pair(case_id="case_factor", created_at="2026-10-01T10:00:00")
    lm.prepare_training_pair(pair)
    write_case(training_dir, pair)
    rules = lm.mapping_rules(training_dir)
    product = rules["профиль потолочный"]
    assert product["quantity_mode"] == "factor"
    assert Decimal(product["quantity_factor"]) == Decimal("2")
    assert product["unit"] == "шт" and product["case_id"] == "case_factor"
    service = rules["спрей фиксация"]  # learned alias for the OCR name
    assert service["quantity_mode"] == "service"
    assert Decimal(service["service_quantity"]) == Decimal("1")
    assert service["name"] == "Доставка" and service["unit"] == "усл"


def test_conflicting_factors_mark_key_as_conflict(tmp_path):
    training_dir = tmp_path / "training"
    first = make_pair(case_id="case_a", created_at="2026-10-01T10:00:00")
    lm.prepare_training_pair(first)
    write_case(training_dir, first)
    second = make_pair(case_id="case_b", created_at="2026-10-02T10:00:00")
    second["invoice"]["items"][0]["quantity"] = "8"  # same key, different factor
    lm.prepare_training_pair(second)
    write_case(training_dir, second)
    rules = lm.mapping_rules(training_dir)
    assert rules["профиль потолочный"].get("conflict") is True
    assert lm.source_rule({"name": "Профиль потолочный", "edited": False}, rules) is None


def test_apply_training_pairs_builds_full_items(tmp_path):
    training_dir = tmp_path / "training"
    pair = make_pair(case_id="case_apply", created_at="2026-10-01T10:00:00")
    lm.prepare_training_pair(pair)
    write_case(training_dir, pair)
    receipt = {
        "items": [
            {"row_id": "r1", "name": "Профиль потолочный", "edited": False,
             "quantity": "2", "price": "100"},
            {"row_id": "r2", "name": "Спрей фиксация", "edited": False,
             "quantity": "1", "price": "50"},
        ],
        "total": "280", "vat_amount": "30",
    }
    result = lm.apply_training_pairs(receipt, training_dir)
    assert result["status"] == "applied"
    assert len(result["items"]) == 2
    applied = result["items"][0]
    assert applied["quantity"] == "4" and applied["name"] == "Профиль потолочный KNAUF"
    # amounts keep the exact receipt total (250 goods net + 30 tax):
    assert sum((Decimal(row["amount"]) for row in result["items"]), Decimal(0)) == Decimal("280")


def test_real_training_pairs_produce_rules():
    rules = lm.mapping_rules()
    assert len(rules) == 55
    assert not any(rule.get("conflict") for rule in rules.values())
    sample = next(rule for rule in rules.values() if rule["quantity_mode"] == "factor")
    assert all(field in sample for field in ("name", "unit", "quantity_factor", "case_id"))


def test_vat_matches_tolerance():
    assert lm.vat_matches("30.0", "30.00") is True
    assert lm.vat_matches(None, "30") is False
    assert lm.vat_matches("30.99", "30.0") is True
    assert lm.vat_matches("31.0", "30.0") is False
