# -*- coding: utf-8 -*-
"""Диагностика выбора якоря в find_total по файловому дампу слов."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from receipts_ocr.ocr.base import WordBox
from receipts_ocr.parse.anchors import find_total, fuzzy_word, TOTAL_WORDS

tag = sys.argv[1] if len(sys.argv) > 1 else 'chat_20261023_03_paint_666710'
thr_cy = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0

words = []
for ln in open(f'data/eval/debug/{tag}/words.txt', encoding='utf-8'):
    p = ln.rstrip('\n').split('\t')
    if len(p) < 4:
        continue
    conf, cx, cy, t = float(p[0]), float(p[1]), float(p[2]), p[3]
    quad = [(cx - 5, cy - 12), (cx + 5, cy - 12), (cx + 5, cy + 12), (cx - 5, cy + 12)]
    words.append(WordBox(text=t, conf=conf, quad=quad))

out = [f'== {tag} n={len(words)}']
for i, wb in enumerate(words):
    m = fuzzy_word(wb.text, TOTAL_WORDS)
    if m:
        awb = words[i]
        exact = 1 if awb.text.upper().strip('.,:;()«»"=№|-—') == m else 0
        parts = [(wb2.cx, wb2.text) for j, wb2 in enumerate(words)
                 if j != i and wb2.cx > awb.cx
                 and abs(wb2.cy - awb.cy) <= 0.9 * (awb.height + wb2.height) / 2.0 + 10.0]
        out.append(f'hit[{i}] {wb.text!r} cy={wb.cy:.0f} cx={wb.cx:.0f} h={wb.height:.1f}'
                   f' -> {m!r} exact={exact} n_parts={len(parts)} parts={[t for _, t in parts]}')
ttl, via = find_total(words)
out.append(f'TOTAL={ttl!r} via={via!r}')
if thr_cy:
    out.append('--- words cy>thr:')
    for wb in words:
        if wb.cy > thr_cy:
            out.append(f'  cy={wb.cy:5.0f} cx={wb.cx:5.0f} {wb.text!r}')

open('data/eval/debug/tmp_rank.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('done')
