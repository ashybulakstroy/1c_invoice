"""Synthetic + boundary tests for the adapted 1C catalog and proposals (Etap 2).

Real-data boundaries mirror the donor expectations for the shipped workbook
(counts per sheet, code identity). Everything else is synthetic: temporary
xlsx workbooks, a temporary mapping file and a monkeypatched catalog index.
No OCR is involved.
"""
from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from App.invoicing import catalog_1c
from App.invoicing import transform_candidates
from App.invoicing import user_mapping
from App.invoicing.receipt_names import torgsoft_name


def write_xlsx(path, sheets):
    from openpyxl import Workbook
    book = Workbook()
    book.remove(book.active)
    for sheet_name, rows in sheets.items():
        sheet = book.create_sheet(sheet_name)
        for row in rows:
            sheet.append(row)
    book.save(path)
    book.close()


def test_real_workbook_counts_codes_and_inventory_fields():
    digest = hashlib.sha256(next(catalog_1c.CATALOG_DIR.glob("*.xls")).read_bytes()).hexdigest()
    index = catalog_1c.catalog()
    assert index["errors"] == []
    per_sheet = {sheet: sum(row["sheet"] == sheet for row in index["items"])
                 for sheet in ("Товары", "Услуги", "Производство")}
    assert per_sheet == {"Товары": 3701, "Услуги": 11, "Производство": 19}
    concrete = catalog_1c.search_catalog("00000019603")["items"][0]
    assert concrete["name"].startswith("Бетон М350")
    assert concrete["code"] == "00000019603"
    assert concrete["unit"] == "м3" and concrete["service"] is False
    assert concrete["stock_quantity"] == Decimal("630")
    assert concrete["stock_amount"] == Decimal("17592241.37")
    assert concrete["accounting_price"] == Decimal("27924.19")
    assert concrete["warehouse"] == "Склад Алатау" and concrete["snapshot_date"] == "16.10.2026"
    assert catalog_1c.catalog_item(concrete["id"])["code"] == concrete["code"]
    reading = hashlib.sha256(next(catalog_1c.CATALOG_DIR.glob("*.xls")).read_bytes()).hexdigest()
    assert reading == digest


def test_real_workbook_service_and_without_stock_row():
    index = catalog_1c.catalog()
    delivery = catalog_1c.search_catalog("Доставка")["items"][0]
    assert delivery["name"] == "Доставка" and delivery["service"] is True
    assert delivery["unit"] == "усл" and delivery["code"] == "00000002296"
    assert delivery["sheet"] == "Услуги"
    legacy_id = hashlib.sha256("Доставка\0усл".encode()).hexdigest()[:24]
    assert catalog_1c.catalog_item(legacy_id)["code"] == "00000002296"
    pencil = next(row for row in index["items"] if row["name"] == "Строительный карандаш")
    assert pencil["code"] == "00000007681"
    assert pencil["stock_quantity"] is None  # absent data marked unknown, not invented


def test_synthetic_duplicate_names_distinct_codes(tmp_path):
    path = tmp_path / "test_catalog.xlsx"
    write_xlsx(path, {
        "Товары": [
            [""],
            ["№", "Номенклатура", "", "", "Код / Артикул", "Ед.изм."],
            ["1", "Профиль потолочный", "", "", "0000000001A", "шт"],
            ["2", "Профиль потолочный", "", "", "0000000001B", "шт"],
            ["3", "Итого", "", "", "", ""],
        ],
        "Услуги": [
            ["", ""],
            ["", "Услуги базы"],
            ["", "Номенклатура", "Код"],
            ["", "Доставка склада", "0000000003"],
        ],
    })
    index = catalog_1c.catalog(tmp_path)
    assert index["errors"] == []
    items = [row for row in index["items"] if row["sheet"] == "Товары"]
    assert sorted(row["code"] for row in items) == ["0000000001A", "0000000001B"]
    assert all(row["warehouse"] is None and row["snapshot_date"] is None for row in items)
    exact = catalog_1c.search_catalog("0000000001A", directory=tmp_path)["items"]
    assert len(exact) == 1 and exact[0]["name"] == "Профиль потолочный"
    delivery = [row for row in index["items"] if row["sheet"] == "Услуги"]
    assert delivery and delivery[0]["service"] is True and delivery[0]["unit"] == "усл"


def test_synthetic_second_header_row_stock(tmp_path):
    path = tmp_path / "Склад Тестовый на 01.02.2026.xlsx"
    write_xlsx(path, {"Товары": [
        [""],
        [""],
        ["№ п/п", "Номенклатура", "", "", "Код / Артикул", "Ед.изм.",
         "Конечный остаток", "", ""],
        ["", "", "", "", "", "", "Учетная цена", "Количество", "Сумма"],
        ["1", "Бетон тестовый", "", "", "0000000009", "м3", "10.5", "4", "42"],
        ["2", "Кирпич тестовый", "", "", "0000000010", "шт", "", "", ""],
    ]})
    index = catalog_1c.catalog(tmp_path)
    assert index["errors"] == []
    concrete = next(row for row in index["items"] if row["name"] == "Бетон тестовый")
    assert concrete["stock_quantity"] == Decimal("4")
    assert concrete["stock_amount"] == Decimal("42")
    assert concrete["accounting_price"] == Decimal("10.5")
    assert concrete["warehouse"] == "Склад Тестовый" and concrete["snapshot_date"] == "01.02.2026"
    brick = next(row for row in index["items"] if row["name"] == "Кирпич тестовый")
    assert brick["stock_quantity"] is None


def test_user_mapping_store_roundtrip(tmp_path):
    mapping_file = tmp_path / "mapping.txt"
    with mapping_file.open("w", encoding="utf-8-sig", newline="") as source:
        writer = csv.writer(source, delimiter="\t")
        writer.writerows([["Плёнка пвх", "Плёнка ПВХ"], ["Сумка以防", "Сумки"]])
    assert user_mapping.lookup_user_mapping("Плёнка ПВХ", mapping_file) == "Плёнка ПВХ"
    assert user_mapping.lookup_user_mapping("сумка 防", mapping_file) == "Сумки"
    assert user_mapping.lookup_user_mapping("нет", mapping_file) is None
    assert user_mapping.save_user_mappings([("плёнка пвх", "Плёнка ПВХ")], mapping_file) == 1
    assert user_mapping.lookup_user_mapping("Плёнка ПВХ", mapping_file) == "Плёнка ПВХ"


def test_confirmed_key_semantics_in_receipt_names():
    assert torgsoft_name({"name": "Подтверждённое", "ocr_name": "сырое", "edited": True}) == "Подтверждённое"
    assert torgsoft_name({"name": "сырое", "ocr_name": "сырое", "edited": False}) == "сырое"
    assert torgsoft_name({"from_mapping": True, "reference_name": "справочник"}) == "справочник"


def test_real_candidates_load_with_ten_variants():
    index = transform_candidates.candidate_index()
    assert index["file"] == "torgsoft_1c_transform_top10.json"
    assert index["invalid_records"] == 0 and index["errors"] == []
    assert index["rows"]
    assert any(len(row["candidates_1c"]) == 10 for row in index["rows"])


def test_proposals_join_catalog_and_preserve_stock():
    source = {"name": "TYTAN Краска аэрозольная коричневая 400 мл", "ocr_name": "краска аэрозоль",
              "edited": True, "article": "9783734"}
    index = transform_candidates.candidate_index()
    resolved = transform_candidates.resolve_source(source, "9783734", index)
    assert resolved["status"] == "resolved"
    items = transform_candidates.proposals(source, "9783734")["items"]
    assert len(items) == 10
    top = items[0]
    assert top["rank"] == 1 and top["code"] == "00000014316"
    assert Decimal(str(top["stock_snapshot"])) == Decimal("7.0")
    assert top["stock_date"] == "16.10.2026"
    assert top["name"] == "TYTAN Краска аэрозольная коричневая 400 мл" and top["unit"] == "шт"


def test_proposals_flags_catalog_drift(monkeypatch):
    fake_index = {"by_code": {"00000014316": [{"id": "x", "name": "Актуальная карточка 1С", "unit": "шт",
                                               "service": False, "code": "00000014316"}]}}
    monkeypatch.setattr(transform_candidates, "catalog", lambda *args, **kwargs: fake_index)
    source = {"name": "Краска", "ocr_name": "краска аэрозоль", "edited": True, "article": "9783734"}
    result = transform_candidates.proposals(source, "9783734")
    assert len(result["items"]) == 1
    assert result["items"][0]["name"] == "Актуальная карточка 1С"
    assert any("Карточка изменилась" in note for note in result["items"][0]["review_notes"])


def test_article_collision_never_auto_resolves(tmp_path):
    rows = [
        proposal_row("TS-1", "9783734", "Краска первая", [dict(RANK_CANDIDATE)]),
        proposal_row("TS-2", "9783734", "Краска вторая", [dict(RANK_CANDIDATE)]),
    ]
    path = candidate_file(tmp_path, rows)
    index = transform_candidates.candidate_index(path)
    source = {"name": "Краска первая", "ocr_name": None, "edited": False}
    resolved = transform_candidates.resolve_source(source, "9783734", index)
    assert resolved["status"] == "source_required"
    assert len(resolved["source_options"]) == 2


def test_invalid_schema_is_reported(tmp_path):
    path = tmp_path / "top10.json"
    path.write_text(json.dumps({"schema_version": "9.9"}), encoding="utf-8")
    index = transform_candidates.candidate_index(path)
    assert index["rows"] == [] and any("Неверный формат" in error for error in index["errors"])


def proposal_row(row_id, article, name, candidates):
    return {
        "row_id": row_id,
        "torgsoft": {"article": article, "name": name, "sources": ["первый этаж"]},
        "search_result": "",
        "candidates_1c": candidates,
        "user_choice": {"selected_code_1c": None, "approved_codes_1c": [],
                        "mapping_status": "not_confirmed", "quantity_coefficient": None},
    }


RANK_CANDIDATE = {
    "rank": 1, "code_1c": "0000000001", "name_1c": "Карточка 1С",
    "source_sheet": "Товары", "unit_1c": "шт", "stock_snapshot": "1.0",
    "stock_date": "01.02.2026", "review_notes": [],
}


def candidate_file(tmp_path, rows):
    data = {"schema_version": "1.0", "candidate_limit": 10, "confirmed_mapping": False,
            "sources": [], "notes": [], "rows": rows}
    path = tmp_path / "top10.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
