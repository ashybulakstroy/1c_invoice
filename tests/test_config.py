"""Тесты настроек: .env-парсер, приоритеты, типизация, override."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from receipts_ocr.loadenv import parse_env_text
from receipts_ocr.settings import override, reset_settings


class TestParseEnv(unittest.TestCase):
    def test_basic_and_skips(self):
        txt = "# комментарий\nA=1\nB = hello world \nC='x=y'\nD=\"q\"\nБЕЗРАВНО\nE=\n"
        self.assertEqual(parse_env_text(txt), {"A": "1", "B": "hello world", "C": "x=y", "D": "q", "E": ""})

    def test_quotes_stripped(self):
        self.assertEqual(parse_env_text('K="0.0.0.0"'), {"K": "0.0.0.0"})


class TestSettings(unittest.TestCase):
    def setUp(self):
        reset_settings()

    def test_values_from_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text("# web\nOCR_WEB_PORT=8017\nOCR_MAX_SIDE=1700\nOCR_VISUALIZE=1\n", encoding="utf-8")
            from receipts_ocr.settings import load_settings
            s = load_settings(env_file=p)
        self.assertEqual(s.web_port, 8017)
        self.assertEqual(s.max_side, 1700)
        self.assertTrue(s.visualize)
        self.assertFalse(s.doc_detect is False)

    def test_env_wins_over_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text("OCR_WEB_PORT=8018\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"OCR_WEB_PORT": "9001"}):
                from receipts_ocr.settings import load_settings
                s = load_settings(env_file=p)
            self.assertEqual(s.web_port, 9001)

    def test_override_validates(self):
        override(max_side=1234)
        from receipts_ocr.settings import get_settings
        self.assertEqual(get_settings().max_side, 1234)
        with self.assertRaises(ValueError):
            override(nope=1)


if __name__ == "__main__":
    unittest.main()
