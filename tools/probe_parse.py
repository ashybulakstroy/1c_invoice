# -*- coding: utf-8 -*-
"""Офлайн-проба detect_table + rows_from_table на свалках слов/стадий."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2

from receipts_ocr.layout.table import detect_table
from receipts_ocr.parse.rows import rows_from_table


class WB:
    def __init__(self, text, cx, cy, h=24.0):
        self.text, self.cx, self.cy, self.conf = text, cx, cy, 0.9
        self.height, self.width = h, 10.0
        self.quad = [(cx - 5, cy - h / 2), (cx + 5, cy - h / 2),
                     (cx + 5, cy + h / 2), (cx - 5, cy + h / 2)]


tags = [
    'WhatsApp Image 2026-10-16 at 10.56.23',  # cement
    'chat_20261023_02_hinges_21251',
    'chat_20261023_03_paint_666710',
    'chat_20261023_05_tools_189266',
    'chat_20261023_04_electrical_1647618',
    'WhatsApp Image 2026-10-16 at 13.24.16',  # klei
]
out = []
for tag in tags:
    words = []
    for ln in open(f'data/eval/debug/{tag}/words.txt', encoding='utf-8'):
        p = ln.rstrip('\n').split('\t')
        if len(p) < 4:
            continue
        words.append(WB(p[3], float(p[1]), float(p[2])))
    img = cv2.imread(f'data/eval/debug/{tag}/06_S6_enhance.png')
    tbl = detect_table(img, words)
    if tbl is None:
        out.append(f'== {tag} -> None')
        continue
    rows = rows_from_table(tbl)
    out.append(f'== {tag}: {tbl.nrows}x{tbl.ncols} cols={[(int(a), int(b)) for a, b in tbl.cols]}')
    for r in rows:
        out.append(f'   {r.name[:34]:<34} qty={r.qty} price={r.price} sum={r.sum} {r.kind}')

open('data/eval/debug/tmp_parse.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('done')
