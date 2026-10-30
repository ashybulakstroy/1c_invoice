"""API-key protection for the 1C exchange endpoints.

The operator page stays open by the user's decision; only ``/tasks/*`` is
protected. The key is created once on the server and passed to 1C out of band.
It is never put into a URL, a log line or a downloaded task document.
"""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from App.ocr_catalog_eval import ROOT

HEADER = "X-API-Key"
DEFAULT_KEY_PATH = ROOT / "Data" / "network_api_key.txt"
ENV_KEY = "OCR_EXCHANGE_API_KEY"


class ExchangeAuth:
    """Reads or creates the exchange key and compares it in constant time."""

    def __init__(self, path=None, value=None):
        self.path = Path(path) if path is not None else DEFAULT_KEY_PATH
        self.value = (value if value is not None else os.environ.get(ENV_KEY, "")).strip()
        if not self.value:
            self.value = self._load_or_create()

    def _load_or_create(self) -> str:
        try:
            key = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
        if not key:
            key = secrets.token_hex(32)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(key + "\n", encoding="utf-8")
        return key

    def check(self, value) -> bool:
        if not value or not self.value:
            return False
        return hmac.compare_digest(str(value).strip(), self.value)
