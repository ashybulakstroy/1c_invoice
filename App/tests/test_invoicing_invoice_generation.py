"""Synthetic tests for invoice generation, document printing and mapping memory (Etap 4).

Real cues are avoided where they could hide effects: the confirmed-knowledge
path is patched per test, item names are unique, and `database_id="local"` is
pinned. The PDF check only verifies a renderable single-page document built
from the screen model.
"""
from __future__ import annotations

import json
from decimal import Decimal
from io import BytesIO

import pytest

from App.invoicing import invoice_generation as ig
from App.invoicing import invoice_pdf
from App.invoicing.user_mapping import normalize_mapping_key

SOURCE = {"row_id": "r1", "name": "Тестовый кирпич Г-77", "ocr_name": "Тестовый кирпич Г-77",
          "edited": False, "quantity": "2", "price": "100"}
RECEIPT = {"items": [SOURCE], "vat_amount": "32", "total": "232"}


@pytest.fixture
def empty_knowledge(tmp_path, monkeypatch):
    path = tmp_path / "Torgsoft_1C_mapping.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ig, "KNOWLEDGE_PATH", path)
    return path


def test_generation_marks_unmatched_rows(empty_knowledge):
    result = ig.build_generation(RECEIPT, database_id="local")
    row = result["items"][0]
    assert row["match_status"] == "unmatched"
    assert Decimal(row["amount"]) == Decimal("232.00")
    assert row["quantity"] == "2"
    assert Decimal(row["price"]) == Decimal("116.00")
    assert row["row_id"] == "r1" and row["source_index"] == 0
    assert row["source_name"] == "Тестовый кирпич Г-77"
    assert any("Выберите номенклатуру 1С" in message for message in result["warnings"])
    assert result["total"] == "232" and result["vat_amount"] == "32"
    assert result["status"] == "review"


def test_generation_applies_manual_selection(empty_knowledge):
    selection = {"name": "Кирпич 1С Тестовый", "unit": "шт", "quantity": "4",
                 "code": None, "catalog_id": None,
                 "source_fingerprint": ig.source_fingerprint(SOURCE)}
    result = ig.build_generation(RECEIPT, selections={"r1": selection}, database_id="local")
    row = result["items"][0]
    assert row["match_status"] == "manual"
    assert row["name"] == "Кирпич 1С Тестовый" and row["unit"] == "шт"
    assert row["quantity"] == "4"
    assert Decimal(row["price"]) == Decimal("58")
    assert Decimal(row["amount"]) == Decimal("232.00")
    assert row["code"] is None
    assert result["warnings"] == [] and result["status"] == "applied"


def test_stale_fingerprint_is_never_silent(empty_knowledge):
    selection = {"name": "Кирпич 1С Тестовый", "unit": "шт", "quantity": "4",
                 "source_fingerprint": "0" * 64}
    result = ig.build_generation(RECEIPT, selections={"r1": selection}, database_id="local")
    row = result["items"][0]
    assert row["match_status"] == "unmatched" and row["name"] is None
    assert any("Повторно проверьте связь" in message for message in result["warnings"])


def test_generation_uses_remembered_service_rule(empty_knowledge):
    rule = {"catalog_id": None, "name": "Тестовая услуга Z", "unit": "усл", "code": None,
            "quantity_factor": "1", "service_quantity": "1", "service": True}
    path = empty_knowledge
    path.write_text(json.dumps({normalize_mapping_key(SOURCE["name"]): rule}, ensure_ascii=False),
                    encoding="utf-8")
    result = ig.build_generation(RECEIPT, database_id="local")
    row = result["items"][0]
    assert row["match_status"] == "remembered"
    assert row["name"] == "Тестовая услуга Z" and row["service"] is True
    assert row["quantity"] == "1"
    assert Decimal(row["price"]) == Decimal("232")
    assert result["status"] == "applied"


def test_remember_selections_moves_name_rule_and_backs_up(empty_knowledge):
    selection = {"name": "Кирпич 1С Тестовый", "unit": "шт", "quantity": "4",
                 "catalog_id": None, "code": None}
    ig.remember_selections([(SOURCE, selection)], path=empty_knowledge, database_id="local")
    stored = json.loads(empty_knowledge.read_text(encoding="utf-8"))
    assert stored[normalize_mapping_key(SOURCE["name"])]["quantity_factor"] == "2"
    history = empty_knowledge.parent / "history"
    assert not (history / "").exists() or list(history.glob("*")) == []
    # Each further successful rewrite leaves a versioned backup file behind.
    for number in range(2, 8):
        ig.remember_selections(
            [(SOURCE, {**selection, "quantity": str(number)})],
            path=empty_knowledge, database_id="local")
        backups = sorted(history.glob("Torgsoft_1C_mapping_*.json"))
        assert len(backups) <= 5


def test_remember_selections_rejects_contradiction_in_one_batch(empty_knowledge):
    first = {"name": "Кирпич 1С Тестовый", "unit": "шт", "quantity": "4", "catalog_id": None, "code": None}
    second = {"name": "Кирпич 1С Тестовый", "unit": "шт", "quantity": "8", "catalog_id": None, "code": None}
    with pytest.raises(ValueError, match="разные связи"):
        ig.remember_selections([(SOURCE, first), (SOURCE, second)], path=empty_knowledge,
                               database_id="local")


def test_confirmed_candidates_need_positive_quantity(empty_knowledge):
    empty = dict(SOURCE, quantity="0")
    assert ig.confirmed_candidates(empty, Decimal("100"), database_id="local") == []


def test_invoice_document_ready_and_token_stable():
    generation = {"items": [], "total": "232.00", "vat_amount": "32.00",
                  "warnings": [], "status": "applied"}
    receipt = {"date": "16.10.2026", "order_number": "1234"}
    document = ig.invoice_document(receipt, generation)
    assert document["ready"] is True
    assert document["number"] == "OCR-1234"
    assert document["date"] == "16.10.2026"
    assert "Алатау" in document["issuer"]["name"]
    again = ig.invoice_document(receipt, generation)
    assert document["token"] == again["token"]
    form = document["print_form"]
    assert form["total"] == "232,00"
    assert form["amount_words"] == "Двести тридцать два теңге 00 тиын"
    assert form["items"] == []


def test_invoice_document_errors_block_printing():
    generation = {"items": [], "total": "232.00", "vat_amount": "32.00",
                  "warnings": [], "status": "applied"}
    document = ig.invoice_document({"date": "16/10/2026", "order_number": None}, generation)
    assert document["ready"] is False
    assert any("Исправьте дату чека" in message for message in document["errors"])
    assert any("номер заказа" in message for message in document["errors"])
    assert document["number"] == "OCR-"


def generation_document():
    items = [{"row_id": "r1", "name": "Тестовая услуга Z", "unit": "усл", "quantity": "1",
              "price": "232.00", "amount": "232.00", "match_status": "remembered",
              "service": True, "code": None, "catalog_id": None, "source_index": 0,
              "source_name": "Тестовый кирпич Г-77", "source_quantity": "2",
              "source_price": "100", "source_amount": "200"}]
    generation = {"items": items, "total": "232.00", "vat_amount": "32.00",
                  "warnings": [], "status": "applied"}
    return ig.invoice_document({"date": "16.10.2026", "order_number": "777"}, generation)


def test_pdf_renders_single_page():
    document = generation_document()
    payload = invoice_pdf.render_invoice_pdf(document)
    assert isinstance(payload, bytes) and len(payload) > 3000
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(payload))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text() or ""
    assert "232,00" in text


def test_pdf_multi_page_and_long_cyrillic_names():
    from pypdf import PdfReader
    long_name = "Профиль потолочный направляющий KNAUF ППН 2,5×5,0 см толщ. 0,55 мм (3 м), оцинк. (сверхдлинная позиция)"
    items = []
    for index in range(28):
        items.append({"row_id": f"r{index}", "name": (long_name if index % 3 == 0 else f"Тестовый товар {index}"),
                      "unit": "шт", "quantity": str(index + 1), "price": "10.00",
                      "amount": f"{(index + 1) * 10}.00", "match_status": "manual",
                      "service": False, "code": "000000001", "catalog_id": None,
                      "source_index": index, "source_name": f"Строка чека {index}",
                      "source_quantity": "1", "source_price": "10", "source_amount": f"{(index + 1) * 10}.00"})
    total = sum((index + 1) * 10 for index in range(28))
    generation = {"items": items, "total": str(total) + ".00", "vat_amount": "0.00",
                  "warnings": [], "status": "applied"}
    document = ig.invoice_document({"date": "16.10.2026", "order_number": "888"}, generation)
    assert document["ready"] is True
    payload = invoice_pdf.render_invoice_pdf(document)
    reader = PdfReader(BytesIO(payload))
    assert len(reader.pages) >= 2
    text = " ".join((page.extract_text() or "") for page in reader.pages)
    assert "KNAUF ППН" in text
    assert f"Всего наименований {len(items)}" in text
    from App.invoicing.invoice_presentation import print_number
    assert print_number(total) in text


def test_print_number_matches_donor_format():
    from App.invoicing.invoice_presentation import print_number
    assert print_number("116") == "116,00"
    assert print_number("0.5", minimum=3) == "0,500"
    assert print_number(None) == ""
