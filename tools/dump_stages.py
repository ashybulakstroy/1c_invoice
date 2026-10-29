"""Диагностика: PNG всех стадий + слова OCR в файл.

python tools/dump_stages.py <изображение> [--skip-docs] [--out data/eval/debug]
"""
from __future__ import annotations

import cv2
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipts_ocr.io.loader import load_image
from receipts_ocr.layout.lines import group_lines
from receipts_ocr.layout.table import detect_table
from receipts_ocr.observe import overlay_boxes
from receipts_ocr.ocr.session import get_engine
from receipts_ocr.parse.anchors import fuzzy_word, find_total
from receipts_ocr.preproc.detect_doc import find_document_quad, warp_document
from receipts_ocr.preproc.deskew import deskew
from receipts_ocr.preproc.dewarp import dewarp
from receipts_ocr.preproc.enhance import enhance
from receipts_ocr.preproc.orientation import detect_text_rotation
from receipts_ocr.preproc.quality import assess
from receipts_ocr.settings import get_settings


def main() -> int:
    import sys as _s
    for st in (_s.stdout, _s.stderr):         # cp1251-консоль не должна ронять вывод
        try:
            st.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    src = Path(sys.argv[1])
    out_dir = Path("data/eval/debug") / src.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    s = get_settings()

    def save(name: str, img) -> None:
        cv2.imwrite(str(out_dir / f"{name}.png"), img)
        print(f"  saved {name}.png {img.shape}")

    loaded = load_image(src, s.max_side)
    img = loaded.img
    print(f"orig {loaded.orig_w}x{loaded.orig_h} -> {img.shape[1]}x{img.shape[0]} "
          f"warn={loaded.warnings}")
    save("00_S0_load", img)
    q = assess(img)
    print(f"quality: blur={q.blur:.1f} bright={q.brightness:.1f} contrast={q.contrast:.1f} flags={q.flags}")

    qi = find_document_quad(img)
    print(f"doc: found={qi.found} area={qi.area_ratio:.2f} notes={qi.notes}")
    if qi.found and qi.area_ratio >= 0.15:
        img, wh = warp_document(img, qi.quad)
        save("02_S2_doc", img)
        print(f"  doc warp -> {wh}")
    rot = detect_text_rotation(img)
    print(f"rotation: {rot}")
    if rot == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        save("03_S3_rot", img)
    img, wmeta = dewarp(img)
    print(f"dewarp: {wmeta}")
    save("04_S4_dewarp", img)
    img, ang = deskew(img)
    print(f"deskew: {ang}")
    save("05_S5_deskew", img)
    img, steps = enhance(img, q)
    print(f"enhance: {steps}")
    save("06_S6_enhance", img)

    engine = get_engine(s)
    words = engine.ocr(img).words
    print(f"words: {len(words)}")
    for i, wb in enumerate(words):
        print(f"  [{i:3d}] conf={wb.conf:.2f} y={wb.cy:7.1f} x={wb.cx:7.1f} {wb.text!r}")
    if words:
        save("07_S7_words", overlay_boxes(img, words))
    lines = group_lines(words)
    print("lines:")
    for ln in lines:
        print(f"  y={ln.cy:7.1f} {ln.text}")
    table = detect_table(img, words)
    print(f"table: {'None' if table is None else f'{table.nrows}x{table.ncols}'}")
    if table is not None:
        from receipts_ocr.observe import overlay_grid
        save("09_S9_grid", overlay_grid(img, table))
        print(f"  rows: {table.rows}")
        print(f"  cols: {table.cols}")
    tv, tw = find_total(words)
    print(f"total: {tv} via {tw}")

    with (out_dir / "words.txt").open("w", encoding="utf-8") as f:
        for wb in words:
            f.write(f"{wb.conf:.3f}\t{wb.cx:.0f}\t{wb.cy:.0f}\t{wb.text}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
