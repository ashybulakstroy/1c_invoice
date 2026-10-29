# -*- coding: utf-8 -*-
"""Слова в заданной полосе cy из дампа (для поиска хедера «Саны» у электрика)."""
import sys

tag = sys.argv[1]
lo = float(sys.argv[2])
hi = float(sys.argv[3])
out = []
for ln in open(f'data/eval/debug/{tag}/words.txt', encoding='utf-8'):
    p = ln.rstrip('\n').split('\t')
    if len(p) < 4:
        continue
    conf, cx, cy, t = float(p[0]), float(p[1]), float(p[2]), p[3]
    if lo <= cy <= hi:
        out.append(f'cy={cy:5.0f} cx={cx:5.0f} conf={conf:.2f} {t!r}')
open('data/eval/debug/tmp_zone.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('done')
