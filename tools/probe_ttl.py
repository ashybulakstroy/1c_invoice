# -*- coding: utf-8 -*-
"""probe_ttl: офлайн-эксперимент find_total на сдампленных словах.
Варианты:
  base     — текущий find_total();
  vat      — исключение money-частей строки НДС (слово НДС рядом, вне строки итого);
  repair   — vat + ремонт токена вида «46 85400» (digit-group c пропавшей запятой).
Результат: data/eval/debug/tmp_ttl2.txt (UTF-8), читать read-инструментом.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from receipts_ocr.ocr.base import WordBox
from receipts_ocr.parse.anchors import fuzzy_word, TOTAL_WORDS, VAT_WORDS, _row_tol, ln_split
from receipts_ocr.parse.grammar import classify, join_thousands, clean_token


def load_words(tag: str) -> list[WordBox]:
    words = []
    src = Path(f'data/eval/debug/{tag}/words.txt')
    for ln in src.read_text(encoding='utf-8').splitlines():
        p = ln.rstrip('\n').split('\t')
        if len(p) < 4:
            continue
        conf, cx, cy, t = float(p[0]), float(p[1]), float(p[2]), p[3]
        quad = [(cx - 5, cy - 12), (cx + 5, cy - 12), (cx + 5, cy + 12), (cx - 5, cy + 12)]
        words.append(WordBox(text=t, conf=conf, quad=quad))
    return words


def find_total_v(words, *, vat_exclude: bool, repair: bool, strip_tail: bool = False):
    hits: list[tuple[int, str]] = []
    consumed: set[int] = set()
    for i, wb in enumerate(words):
        w = fuzzy_word(wb.text, TOTAL_WORDS)
        if w:
            hits.append((i, w))
    if not hits:
        short = [(i, wb) for i, wb in enumerate(words)
                 if 1 <= len(wb.text.strip()) <= 6]
        for ia, a in short:
            for ib, b in short:
                if ib == ia:
                    continue
                if abs(a.cy - b.cy) > 12 or not (0 < b.cx - a.cx <= 80):
                    continue
                take = None
                t2 = a.text.strip() + b.text.strip()
                if fuzzy_word(t2, TOTAL_WORDS):
                    take = (t2, (ia, ib))
                else:
                    for ic, c in short:
                        if ic in (ia, ib):
                            continue
                        if abs(b.cy - c.cy) > 12 or not (0 < c.cx - b.cx <= 80):
                            continue
                        t3 = t2 + c.text.strip()
                        if fuzzy_word(t3, TOTAL_WORDS):
                            take = (t3, (ia, ib, ic))
                            break
                if take:
                    hits.append((ia, take[0]))
                    consumed = set(take[1])
                    break
            if hits:
                break
    if not hits:
        return None, None

    vat_rows: list[tuple[float, WordBox]] = []
    if vat_exclude:
        for j, vwb in enumerate(words):
            if any(fuzzy_word(t, VAT_WORDS) for t in ln_split(vwb.text)):
                vat_rows.append((j, vwb))
    def _rank(hit):
        i, m = hit
        awb = words[i]
        exact = 1 if awb.text.upper().strip(".,:;()«»\"=№|-—") == m else 0
        n_parts = sum(1 for j, wb in enumerate(words)
                      if j not in consumed and j != i and wb.cx > awb.cx
                      and abs(wb.cy - awb.cy) <= _row_tol(awb.height, wb.height))
        return (exact, n_parts, i)

    anchor = max(hits, key=_rank)
    awb = words[anchor[0]]
    parts: list[tuple[float, str]] = []
    for j, wb in enumerate(words):
        if j in consumed:
            continue
        if abs(wb.cy - awb.cy) > _row_tol(awb.height, wb.height):
            continue
        if wb.cx <= awb.cx:
            continue
        if vat_rows:
            dy_a = abs(wb.cy - awb.cy)
            in_vat = any(
                abs(wb.cy - vwb.cy) < 0.7 * dy_a
                for _, vwb in vat_rows)
            if in_vat:
                continue
        parts.append((wb.cx, wb.text))
    if not parts:
        return None, anchor[1]
    parts.sort()
    texts = [t for _, t in parts]
    if strip_tail:
        # «658,00 7» / «17 400,00 7]» → «658,00» / «17 400,00»:
        # OCR-хвост после money с копейками — мисрид валютного т/г и скобок
        texts = [re.sub(r"^(.*[.,]\d{2})\s*(?:7)?\]*\s*$", r"\1", t) for t in texts]
    tokens = join_thousands(texts)
    if repair:
        fixed: list[str] = []
        for tok in tokens:
            t = clean_token(tok).rstrip("]").lstrip("[").strip()
            # «46 85400» / «46 85400 ]»: две digit-группы без запятой;
            # 5-значный хвост = «XXX.EE» с потерянной запятой (Torgsoft печатает ,00)
            if re.fullmatch(r"\d{1,3} \d{5}", t):
                a, b = t.split(" ")
                fixed.append(f"{a} {b[:3]}.{b[-2:]}")
                continue
            fixed.append(tok)
        tokens = fixed
    value = None
    dec_value = None
    for tok in tokens:
        c = classify(tok)
        if (c is None or c["kind"] == "mult") and len(tok) > 3:
            for cut in (1, 2):
                c2 = classify(tok[:-cut])
                if c2 and c2["kind"] in ("money", "num") and c2["value"] is not None:
                    c = c2
                    break
        if c and c["kind"] in ("money", "num") and c["value"] is not None:
            value = float(c["value"])
            if c["kind"] == "money" and ("," in tok or "." in tok):
                dec_value = float(c["value"])
    return (dec_value if dec_value is not None else value), anchor[1]


TAGS = [
    'chat_20261023_02_hinges_21251',
    'chat_20261023_03_paint_666710',
    'chat_20261023_04_electrical_1647618',
    'chat_20261023_05_tools_189266',
    'WhatsApp Image 2026-10-16 at 10.18.27',
    'WhatsApp Image 2026-10-16 at 10.56.23',
    'WhatsApp Image 2026-10-16 at 11.26.54',
    'WhatsApp Image 2026-10-16 at 13.10.43',
    'WhatsApp Image 2026-10-16 at 13.00.55',
    'WhatsApp Image 2026-10-16 at 13.24.16',
    'WhatsApp Image 2026-10-16 at 16.31.46',
]

EXPECT = {   # известные верные ttl (batch5/batch6) — регрессией считается расхождение
    'chat_20261023_02_hinges_21251': 21251.0,
    'chat_20261023_03_paint_666710': 666710.0,
    'chat_20261023_05_tools_189266': 189266.0,
    'WhatsApp Image 2026-10-16 at 10.18.27': 17400.0,
    'WhatsApp Image 2026-10-16 at 10.56.23': 67280.0,
    'WhatsApp Image 2026-10-16 at 13.24.16': 4400.0,
}


def main() -> int:
    out = ['tag'.ljust(42), 'base'.rjust(12), 'vat'.rjust(12), 'repair'.rjust(12),
           ' expect', 'verdict']
    reg = 0
    for tag in TAGS:
        words = load_words(tag)
        base = find_total_v(words, vat_exclude=False, repair=False)
        rep = find_total_v(words, vat_exclude=True, repair=True, strip_tail=True)
        exp = EXPECT.get(tag, '-')
        if isinstance(exp, float) and rep[0] != exp:
            verdict = 'REGRESS!'
            reg += 1
        elif rep[0] != base[0]:
            verdict = 'changed'
        else:
            verdict = 'same'
        out.append(f"{tag[:40]:<42}{str(base[0]):>12}{str(rep[0]):>12} "
                   f"{str(exp):>10}  {verdict}")
    out.append(f"REGRESSIONS: {reg}")
    Path('data/eval/debug/tmp_ttl2.txt').write_text('\n'.join(out), encoding='utf-8')
    print('done')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(errors='replace')
    raise SystemExit(main())
