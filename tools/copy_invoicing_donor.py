"""One-shot migration of donor generation modules into App/invoicing.

Copies donor sources with precise, counted transformations. Fails loudly when
any expected replacement is missing. Run from the project root once:
  .venv/Scripts/python.exe -X utf8 tools/copy_invoicing_donor.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DONOR = Path(r"R:/Experiment_Torgsoft_1C_Transformation_Invoice/donor_sources/App")
PROJECT = Path(__file__).resolve().parents[1]
TARGET = PROJECT / "App" / "invoicing"

BACKUP_HELPER = '''

def _backup_knowledge(path):
    """Versioned backup of user-confirmed mapping rules before any rewrite."""
    import shutil
    import time
    if not Path(path).exists():
        return
    history = Path(path).parent / "history"
    history.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, history / f"{Path(path).stem}_{stamp}.json")
    backups = sorted(history.glob(f"{Path(path).stem}_*.json"))
    for stale in backups[:-5]:
        stale.unlink()
'''


def apply(text: str, replacements: list[tuple[str, str, int]]) -> str:
    for old, new, expected in replacements:
        count = text.count(old)
        if count != expected:
            raise SystemExit(f"{old!r}: ожидалось {expected}, найдено {count}")
        text = text.replace(old, new)
    leftovers = re.findall(r"^(?:from|import)\s+App\.(?!invoicing)\S+", text, flags=re.MULTILINE)
    if leftovers:
        raise SystemExit(f"остались донорские импорты: {leftovers}")
    return text


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    files = {
        "invoice_presentation.py": [],
        "invoice_pdf.py": [
            ("from App.invoice_presentation import print_fields",
             "from App.invoicing.invoice_presentation import print_fields", 1),
        ],
        "invoice_generation.py": [
            ("from App.learned_mapping import apply_training_pairs, training_alternatives, CENT, VAT_TOLERANCE",
             "from App.invoicing.learned_mapping import apply_training_pairs, training_alternatives, CENT, VAT_TOLERANCE", 1),
            ("from App.user_mapping import normalize_mapping_key",
             "from App.invoicing.user_mapping import normalize_mapping_key", 1),
            ("from App.catalog_1c import catalog_item, catalog_named_item, suggest_catalog",
             "from App.invoicing.catalog_1c import catalog_item, catalog_named_item, suggest_catalog", 1),
            ("from App.receipt_names import torgsoft_name",
             "from App.invoicing.receipt_names import torgsoft_name", 1),
            ("from App.invoice_presentation import print_fields",
             "from App.invoicing.invoice_presentation import print_fields", 1),
            ("from App.transform_candidates import resolve_source",
             "from App.invoicing.transform_candidates import resolve_source", 1),
            ("ROOT = Path(__file__).resolve().parents[1]",
             "ROOT = Path(__file__).resolve().parents[2]", 1),
        ],
    }
    for name, replacements in files.items():
        text = apply((DONOR / name).read_text(encoding="utf-8"), replacements)
        if name == "invoice_generation.py":
            marker = "\n\ndef transformed_numbers("
            if marker not in text:
                raise SystemExit("маркер вставки бэкапа не найден")
            text = text.replace(marker, BACKUP_HELPER + marker, 1)
        (TARGET / name).write_text(text, encoding="utf-8")
        print("written:", TARGET / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
