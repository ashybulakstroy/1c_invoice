"""Тесты грамматики чисел RU/KZ (реальные форматы из Dataset Тапсырыс-чеков)."""

import unittest

from receipts_ocr.parse import grammar as g


class TestParseValue(unittest.TestCase):
    def test_common(self):
        self.assertEqual(g.parse_value("35,00"), 35.0)
        self.assertEqual(g.parse_value("125 929,60"), 125929.6)
        self.assertEqual(g.parse_value("920 т"), 920.0)
        self.assertEqual(g.parse_value("0,524"), 0.524)
        self.assertEqual(g.parse_value("17369,6"), 17369.6)
        self.assertIsNone(g.parse_value("abc"))

    def test_negative_conventions(self):
        self.assertEqual(g.parse_value("=101-00"), -101.0)
        self.assertEqual(g.parse_value("-101-00"), -101.0)
        self.assertEqual(g.parse_value("99,90-"), -99.9)

    def test_currency_suffix(self):
        self.assertEqual(g.parse_value("23 780,00 Т"), 23780.0)
        self.assertEqual(g.parse_value("1 т"), 1.0)


class TestClassify(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(g.classify("118"), {"kind": "num", "value": 118.0, "unit": None})
        self.assertEqual(g.classify("1 Т")["kind"], "num")
        self.assertEqual(g.classify("59,90"), {"kind": "money", "value": 59.9, "unit": None})
        self.assertEqual(g.classify("x")["kind"], "mult")
        c = g.classify("0,524 кг")
        self.assertEqual((c["kind"], c["value"], c["unit"]), ("num", 0.524, "кг"))
        self.assertIsNone(g.classify("Молоко"))

    def test_join_thousands(self):
        self.assertEqual(g.join_thousands(["125", "929,60"]), ["125 929,60"])
        self.assertEqual(g.join_thousands(["23", "780,00"]), ["23 780,00"])
        # защита от ложной склейки: цены с 2-значной целой частью
        self.assertEqual(g.join_thousands(["2", "59,90"]), ["2", "59,90"])
        self.assertEqual(g.join_thousands(["100", "40 т"]), ["100", "40 т"])


if __name__ == "__main__":
    unittest.main()
