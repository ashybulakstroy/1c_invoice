# -*- coding: utf-8 -*-
"""probe_geom: быстрые геом-метрики (спека §9) на S0+S2 без OCR.
Для каждого чека: квод, уверенность, причины отказа, метрики original/warped.
Результат: data/eval/probe_geom.json (UTF-8) — читать read-инструментом.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Work\Projects\Prj_16_OCR")

from receipts_ocr.io.loader import load_image
from receipts_ocr.preproc.detect_doc import MIN_AREA_RATIO, find_document_quad
from receipts_ocr.preproc.rectify import rectify_candidates

IN_DIR = Path(r"C:\Work\Projects\Prj_15_Torgsoft_Check_1C\Data\in_data")
OUT = Path(r"C:\Work\Projects\Prj_16_OCR\data\eval\probe_geom.json")
EXTS = {".jpg", ".jpeg", ".png"}


def main() -> int:
    rows = []
    for p in sorted(q for q in IN_DIR.iterdir() if q.suffix.lower() in EXTS):
        loaded = load_image(str(p), 2000)
        img = loaded.img
        qi = find_document_quad(img)
        row = {
            "file": p.name,
            "found": qi.found,
            "area_ratio": round(qi.area_ratio, 3),
            "notes": list(qi.notes),
        }
        if qi.found and qi.area_ratio >= MIN_AREA_RATIO:
            try:
                _img2, meta = rectify_candidates(img, qi.quad)
                row["method"] = meta["method"]
                row["conf"] = meta["confidence"]
                row["checks"] = meta["checks"]
                row["reason"] = meta.get("reason", "")
                m = meta.get("metrics") or {}
                if m:
                    row["m_orig"] = m.get("original")
                    row["m_warp"] = m.get("warped")
            except Exception as exc:  # noqa: BLE001
                row["method"] = "error"
                row["reason"] = f"{type(exc).__name__}: {exc}"
        else:
            row["method"] = "doc_miss"
        rows.append(row)
        stem = p.stem[:12]
        print(f"done {stem} -> {row['method']}", flush=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK rows={len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    raise SystemExit(main())
