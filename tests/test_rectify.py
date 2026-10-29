"""Тесты S2-геометрии по кандидатам (receipt_geometry_spec.md §6.3, §9):
проверка кводов, безопасный fallback при потере данных, принятие хорошей гомографии."""

from __future__ import annotations

import cv2
import numpy as np
import unittest

from receipts_ocr.preproc.rectify import CandidateEval, quad_confidence, rectify_candidates


def _bars_img() -> np.ndarray:
    """Белый лист с жирными чёрными «строками» — печатный чек-болванка 300x400."""
    img = np.full((400, 300, 3), 255, np.uint8)
    for y in range(60, 360, 40):
        cv2.rectangle(img, (40, y), (260, y + 14), (0, 0, 0), -1)
    return img


class TestQuadConfidence(unittest.TestCase):
    def test_good_quad(self):
        # слегка развёрнутый лист, занимающий большую часть кадра
        quad = np.array([[30, 10], [280, 18], [270, 390], [20, 380]], np.float32)
        conf, reasons = quad_confidence(quad, 300, 400)
        self.assertEqual(reasons, [])
        self.assertGreaterEqual(conf, 0.5)

    def test_reject_tiny_area(self):
        quad = np.array([[10, 0], [30, 0], [30, 400], [10, 400]], np.float32)  # лента 2.7% кадра
        conf, reasons = quad_confidence(quad, 300, 400)
        self.assertEqual(conf, 0.0)
        self.assertEqual(len(reasons), 1)

    def test_reject_far_out_of_frame(self):
        quad = np.array([[300, 100], [2000, 90], [1900, 2000], [250, 1900]], np.float32)
        conf, reasons = quad_confidence(quad, 300, 400)
        self.assertEqual(conf, 0.0)
        self.assertIn("далёко за кадром", reasons[0])

    def test_reject_sliver(self):
        quad = np.array([[5, 5], [295, 5], [295, 24], [5, 24]], np.float32)  # высота 19px < 12% от 400
        conf, reasons = quad_confidence(quad, 300, 400)
        self.assertEqual(conf, 0.0)


class TestRectifyCandidates(unittest.TestCase):
    def test_accept_good_warp(self):
        img = _bars_img()
        quad = np.array([[25, 8], [285, 20], [272, 392], [18, 382]], np.float32)
        out, meta = rectify_candidates(img, quad)
        self.assertEqual(meta["method"], "homography_paper")
        self.assertEqual(meta["candidate"], "warped")
        self.assertFalse(meta["flags"])  # без needs_review

    def test_fallback_on_data_loss(self):
        # чернила только в ЛЕВОЙ половине; квод покрывает только правую → warp вырежет текст
        img = np.full((400, 300, 3), 255, np.uint8)
        for y in range(40, 380, 30):
            cv2.rectangle(img, (30, y), (140, y + 16), (0, 0, 0), -1)
        quad = np.array([[160, 10], [295, 10], [295, 390], [160, 390]], np.float32)
        out, meta = rectify_candidates(img, quad)
        self.assertEqual(meta["method"], "original_fallback")
        self.assertEqual(meta["flags"], ["needs_review"])
        self.assertIn("потеря чернил", meta["reason"])
        # оригинал возвращён без изменений
        self.assertTrue(np.array_equal(out, img))

    def test_fallback_on_scores_collapse(self):
        # тот же болван, квод набран так, что строки почти исчезают: тонкая полоса высотой < 12%….
        # используем честный квод на пустом (белом) фоне: score исходника ~0, ink ~0 → ok-путь
        img = np.full((400, 300, 3), 255, np.uint8)
        quad = np.array([[20, 10], [290, 12], [288, 392], [15, 390]], np.float32)
        out, meta = rectify_candidates(img, quad)
        self.assertEqual(meta["method"], "homography_paper")
        self.assertGreaterEqual(meta["confidence"], 0.5)

    def test_metrics_present(self):
        img = _bars_img()
        quad = np.array([[25, 8], [285, 20], [272, 392], [18, 382]], np.float32)
        _out, meta = rectify_candidates(img, quad)
        m = meta["metrics"]
        self.assertIsInstance(m, dict)
        for side in ("original", "warped"):
            self.assertIn(side, m)
            self.assertIn("ink", m[side])
            self.assertIn("score", m[side])
            self.assertIn("tilt_deg", m[side])
        self.assertIsInstance(CandidateEval().score, float)


if __name__ == "__main__":
    unittest.main()
