"""Тесты S10 якорей и S11/S12 разбора строк (fallback-режим и итог)."""

import unittest

from receipts_ocr.layout.lines import TextLine
from receipts_ocr.parse.anchors import fuzzy_word, find_total, split_zones
from receipts_ocr.parse.rows import parse_line_tokens
from receipts_ocr.ocr.base import WordBox
from receipts_ocr.parse.reconcile import reconcile


def _line(i, text, y=0.0):
    return TextLine(idx=i, text=text, conf=0.9, x0=0, y0=y, x1=100, y1=y + 10)


class TestAnchors(unittest.TestCase):
    def test_fuzzy_kz_words(self):
        self.assertEqual(fuzzy_word("Корытынды:", {"КОРЫТЫНДЫ"}), "КОРЫТЫНДЫ")
        self.assertEqual(fuzzy_word("корытьнды", {"КОРЫТЫНДЫ"}), "КОРЫТЫНДЫ")
        self.assertIsNone(fuzzy_word("СаныОгА", {"ИТОГО", "КОРЫТЫНДЫ"}))

    def test_zones_fallback(self):
        lines = [
            _line(0, "Налоговые данные 16.10.2026"),
            _line(1, "МОРОЖЕНОЕ ВАНИЛЬ 2 59,90 119,80"),
            _line(2, "ХЛЕБ 35,00"),
            _line(3, "ИТОГО 154,80"),
            _line(4, "НАЛИЧНЫМИ 200,00"),
        ]
        z = split_zones(lines)
        self.assertEqual(z.header_end, 1)
        self.assertEqual(z.total_line, 3)
        self.assertEqual(z.items, (1, 2))

    def test_find_total_joins_thousands(self):
        w = lambda t, x, y: WordBox(text=t, conf=0.9,
                                    quad=[(x, y), (x + 60, y), (x + 60, y + 14), (x, y + 14)])
        words = [
            w("Корытынды", 10, 100),
            w(":", 90, 100),
            w("23", 500, 100),
            w("780,00", 560, 100),
            w("Т", 650, 100),
        ]
        value, word = find_total(words)
        self.assertEqual(value, 23780.0)
        self.assertEqual(word, "КОРЫТЫНДЫ")


class TestVatRowExclusion(unittest.TestCase):
    """«1 Т»/сумма НДС не должна быть итогом (13.00.55: ttl=1.0 был баг) и не
    должна вытеснять честный итог (cement 67280 стоял на полпути между VAT и якорем)."""

    W = 60
    H = 24  # высота бокса = реальный шрифт чека; допуск строки 1.2*24+12 = 40.8

    @classmethod
    def _wb(cls, t, cx, cy):
        # (cx, cy) — координаты CENTER из words.txt-дампа: quad = (cx-30, cy-12)…
        return WordBox(text=t, conf=0.99,
                       quad=[(cx - 30, cy - 12), (cx + 30, cy - 12),
                             (cx + 30, cy + 12), (cx - 30, cy + 12)])

    def test_vat_unit_not_total(self):
        # дамп 13.00.55: «1 Т» (НДС-строка) внутри полосы якоря, ttl монолит «46 85400 ]»
        words = [
            self._wb("Корытынды", 127, 706),
            self._wb("НДС 16 %", 175, 658),
            self._wb("6464", 521, 664),
            self._wb("1 Т", 700, 670),
            self._wb("46 85400 ]", 636, 718),
        ]
        value, word = find_total(words)
        self.assertEqual(value, 46854.0)
        self.assertEqual(word, "КОРЫТЫНДЫ")

    def test_money_between_vat_and_anchor_kept(self):
        # дамп cement: ttl-деньги ближе к VAT-строке (20px), чем к якорю (22px), — держим
        words = [
            self._wb("НДС 16 %", 146, 422),
            self._wb("9280", 416, 410),
            self._wb("1 Т", 549, 403),
            self._wb("67 280,00 7", 500, 442),
            self._wb("Корытынды", 108, 464),
        ]
        value, word = find_total(words)
        self.assertEqual(value, 67280.0)
        self.assertEqual(word, "КОРЫТЫНДЫ")

    def test_no_vat_label_legacy(self):
        words = [
            self._wb("Корытынды", 127, 96),
            self._wb("21251", 530, 96),
        ]
        value, _ = find_total(words)
        self.assertEqual(value, 21251.0)


class TestTailNoise(unittest.TestCase):
    """Хвостовой шум OCR после money («658,00 7» — мисрид «т») не должен ломать
    склейку разрядов (11.26.54: ttl был 658 вместо ~45 658)."""

    @staticmethod
    def _wb(t, cx, cy):
        return WordBox(text=t, conf=0.99,
                       quad=[(cx - 30, cy - 12), (cx + 30, cy - 12),
                             (cx + 30, cy + 12), (cx - 30, cy + 12)])

    def test_join_after_noise_strip(self):
        # дамп 11.26.54: якорная строка «…Корытынды 45 658,00 7»
        words = [
            self._wb("Корытынды", 119, 789),
            self._wb("45", 499, 775),
            self._wb("658,00 7", 579, 774),
        ]
        value, word = find_total(words)
        self.assertEqual(value, 45658.0)
        self.assertEqual(word, "КОРЫТЫНДЫ")

    def test_bracket_noise_kept_money(self):
        # как paint: «67 280,00 7» — склейка-одно слово, шум уже был отрезан cut-пути;
        # strip не делает хуже
        words = [
            self._wb("Корытынды", 127, 452),
            self._wb("67 280,00 7", 500, 442),
        ]
        value, _ = find_total(words)
        self.assertEqual(value, 67280.0)


class TestRows(unittest.TestCase):
    def test_qty_price_sum(self):
        row = parse_line_tokens("МОЛОКО 2 59,90 119,80".split())
        self.assertIsNotNone(row)
        self.assertEqual((row.name, row.qty, row.price, row.sum), ("МОЛОКО", 2.0, 59.9, 119.8))

    def test_multiplier_only(self):
        row = parse_line_tokens("1 x 59,90".split())
        self.assertEqual((row.qty, row.price, row.sum), (1.0, 59.9, 59.9))

    def test_weight_row(self):
        row = parse_line_tokens("0,524 кг x 190,00 99,56".split())
        self.assertEqual((row.qty, row.price, row.sum), (0.524, 190.0, 99.56))

    def test_no_numbers(self):
        self.assertIsNone(parse_line_tokens("Кассир Иванов".split()))
        self.assertIsNone(parse_line_tokens([""]))

    def test_reconcile_ok_and_mismatch(self):
        from receipts_ocr.parse.rows import ItemRow
        rows = [ItemRow(idx=0, name="A", qty=4.0, price=1550.0, sum=6200.0),
                ItemRow(idx=1, name="B", qty=10.0, price=1430.0, sum=14300.0),
                ItemRow(idx=2, name="НДС 16 %", qty=3280.0, price=1.0, sum=3280.0, kind="vat")]
        r = reconcile(rows, 23780.0)
        self.assertTrue(r["ok"])
        rows[0].sum = 6000.0
        r2 = reconcile(rows[:2] + [rows[2]], 23780.0)  # ломаем сумму 1-й строки
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["delta"], -200.0)


if __name__ == "__main__":
    unittest.main()
