"""Санити потоков (ARCHITECTURE §5): caps не дают oversubscription в воркерах."""

import unittest

from receipts_ocr.runtime.throttles import apply_thread_caps


class ThreadingSanity(unittest.TestCase):
    def test_caps(self):
        apply_thread_caps(1)
        try:
            import torch
        except ImportError:
            self.skipTest("torch недоступен")
        self.assertEqual(torch.get_num_threads(), 1)
        try:
            import cv2
        except ImportError:
            self.skipTest("cv2 недоступен")
        self.assertLessEqual(cv2.getNumThreads(), 1)


if __name__ == "__main__":
    unittest.main()
