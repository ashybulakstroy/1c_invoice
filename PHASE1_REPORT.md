# Отчёт Фазы 1: OCR предзаказных чеков (grid-таблица, сверка итога)

**Проект:** `Prj_16_OCR` — кассовые чеки/предзаказы Торгсофт (КЗ) → OCR → сверка → 1С
**Дата:** 25.10.2026 · **Статус:** Фаза 1 (точность) — база закреплена, известны границы
**Корпус:** 29 реальных фото чеков из WhatsApp (`C:\Work\Projects\Prj_15_Torgsoft_Check_1C\Data\in_data\`)
**Движок:** EasyOCR (CPU, i5-13400), mag_ratio 2.0, russe/ru словарь — **не менялся** (директива Фазы 2)

## 1. Итоговые цифры

| Прогон | Сошлось (Σ(qty×price) = Корытынды, ⌂0.5) | line-mode | Воркеры | Изменения |
|---|---|---|---|---|
| batch3 | 7/29 | 0 | 6 | header-путь (qz0/pz0, barcap) |
| batch4 | 5/29 | 0 | 6 | — (регресс, откачен) |
| batch5 | **8/29** | 1 | 6 | find_total rating, TOTAL-skip |
| batch6 | **8/29** | 1 | **4** | + geometry по спеке (candidates+fallback) |
| batch7 | **8/29** | 1 | 4 | + VAT-exclusion, money-glue repair |
| batch8 | **8/29** | 1 | 4 | + tail-noise strip |

batch6→batch7 diff: единственное изменение — ttl 13.00.55: 1.0 → **46854.0**
(«1 Т» НДС-строки перестал перебивать итог; честное значение по OCR 46 864,
OCR прочитал «46 85400», repair восстановил 46 854 — расхождение 10 Т уже OCR-уровень).
batch7→batch8 diff: единственное изменение — ttl 11.26.54: 658 → **45658.0**
(хвостовой «7»-мисрид ломал склейку «45»+«658,00»; реальный итог «44 658,00»,
OCR дал «45» — Delta −1000, остаток на OCR-уровне).
Финальный снэпшот: `data/eval/phase1_batch8.json`.

Зелёные чеки (Σ = ttl в ноль): hinges 21251, cement 67280, 13.12.21 58290,
14.24.43 17980, 14.28.10 33408, 15.16.11 21251 (дубль hinges),
14.53.44 42224, 17.48.14 98600 (line-режим).
Дубли в корпусе: 15.16.11 = hinges, 10.45.51 = 01_cropped_long (одинаковые слова/метрики),
т.е. уникально зелёных снимков — 7.

Воркеры снижены 6 → **4** по требованию пользователя (CPU-загрузка; `DEFAULT_WORKERS`
в `runtime/pool.py`). Время пачки выросло умеренно (≈35–47 c/чек wall ≈ 7–8 мин на 29).

## 2. Архитектура пайплайна (не менялась в approved частях)

```
S0 load → S1 quality → S2 doc-quad [rectify: candidates] → S3 rotation → S4 dewarp
  → S5 deskew → S6 enhance → S7 OCR (EasyOCR) → S9 table/grid | S8 lines
  → S10 total-anchors → S11 rows → S12 reconcile
```

- **S9 grid**: header-anchored fast path (`layout/table.py`): колонки и строки от
  хедеров «Саны»/«Багасы» (fuzzy: САНЫ; БАГАСЫ|БАГСЕ|БАГС|БАГСЫ), решётки
  [qx−0.45·wq … pz0] / [pz0 … px+170], pz0 = px−30; геом-путь — fallback.
- **S10**: `find_total` — рейгинг якорей (exact > части справа > ниже по чеку),
  consumed-осколки, строка итога ползёт (`_row_tol`).
- **S12**: `Σ(qty×price)` против «Корытынды»; НДС-строка (Саны=НДС, Багасы=1 Т) —
  это отдельная строка чека, не товарная и не итог.

## 3. Что добавлено в Фазе 1 (по ТЗ `receipt_geometry_spec.md`)

1. **Геометрия-кандидаты (§6.2–6.4, §9):** `preproc/rectify.py` — S2 больше не варпит
   безусловно. Проверка квода (выпуклость, площадь ≥10% кадра, min/max стороны,
   углы ≤35% за кадром) → сравнение кандидатов `original` vs `homography_paper`
   по быстрым метрикам (tilt/curvature/score_lines/ink) → авто-применение только
   без признаков потери данных; иначе **контролируемый fallback** + `needs_review`.
   На корпусе: 22 homography / 7 fallback (01_cropped_long, electrical, 10.45.51,
   13.10.43, 14.24.43, 14.28.10, 16.31.46) — **без потерь против batch5**, оба зелёных
   из fallback-списка (14.24.43, 14.28.10) остались зелёными.
   Отключалось через env `OCR_GEOM_CANDIDATES=0` (для A/B).
2. **VAT-exclusion (`find_total`)**: деньги («1 Т», сумма НДС), что стоят ближе к
   слову/строке НДС, чем к якорю итога (запас 30%), не считаются частями итога.
   Пример: 13.00.55 ttl был 1.0 («1 Т» из соседней строки) → стал 46854.
   cement 67280 остаётся (деньги ближе к VAT всего на 20px против 22px — держим).
3. **Money-glue repair (`find_total`)**: «46 85400 ]» → «46 854.00» — Torgsoft
   печатает «XXX XXX,00», OCR у края листа теряет запятую.
4. **Tail-noise strip (`find_total`)**: хвост «658,00 7» / «17 400,00 7]» → «658,00» /
   «17 400,00» («7» — мисрид валютного «т»). Пример: 11.26.54 ttl был 658 → стал
   45658 (реальный итог «44 658,00», OCR дал «45» — остаток уже на OCR-уровне).
5. **Дефолт воркеров 4** (`runtime/pool.py`), CLI-help обновлён.

## 4. Границы: что НЕ исправлено в Фазе 1 (по дампам)

| Чек | Причина | Фаза 2? |
|---|---|---|
| 10.18.27 | qty «5» отсутствует в words вообще (OCR-пропуск); «30О0 Т]» (буква О) | транслит O→0 в qty/price-зонах — не даст Σ (qty пуст) |
| electrical 1647618 | хедер «Саны» вообще не распознан (каша), ttl «1 647 618,00» осколками | UVDoc/rapidocr; слепые окна не оправданы |
| 16.31.46 | якорь «Корыты/нды» разорван; qty-склейки «3200»+«23»; ttl-денег нет в words | чувствителен к геометрии; после душа прекратится |
| 13.10.43 / 11.26.54 | ttl-осколки (9084/658 — мусор), parse теряет строки | дампы разобраны: 13.10.43 — чек почти пуст по OCR (26 слов, каша); 11.26.54 — floats «45»+«658,00 7» зашит tail-strip'ом (45658); остаток — OCR качестве «45»↔«44» |
| 21 чек «не сошлось» |ocr-пропуски qty/price в длинных таблицах (до 19 строк) | лучшая геометрия/OCR (Фаза 2) |

## 5. Команды / инструменты

```text
python -m receipts_ocr <папка> --workers 4 -o data/eval/phase1_batchN.json
python tools/summarize_batch.py data/eval/phase1_batchN.json
python tools/diff_batch.py data/eval/phase1_batch5.json data/eval/phase1_batch7.json
python tools/probe_geom.py        # S0+S2-метрики без OCR → data/eval/probe_geom.json
python tools/probe_ttl.py         # офлайн find_total на дампах → tmp_ttl2.txt
python tools/dump_stages.py <jpeg> # артефакты стадий → data/eval/debug/<tag>/
```

Тесты: `python -m unittest discover -s tests` — **32 OK** (19 исходных + 8 rectify + 5 ttl).

Artefacts: `data/eval/phase1_batch7.json` — финальный снэпшот; diffs в
`data/eval/batch_diff_*.txt`; geom-проба по всем 29 — `data/eval/probe_geom.json`.

## 6. Изменённые файлы

- `preproc/rectify.py` (новый): quad_confidence / evaluate_candidate / rectify_candidates
- `api.py`: S2 через candidates; поля ReceiptResult geom_method/geom_confidence/geom_metrics
- `settings.py`: `OCR_GEOM_CANDIDATES` (по умолч. True)
- `parse/anchors.py`: _find_vat_rows, _repair_glued_money, VAT-exclusion в find_total
- `runtime/pool.py`: DEFAULT_WORKERS = 4
- `__main__.py`: help воркеров
- `tools/`: probe_geom.py, probe_ttl.py, diff_batch.py (новые)
- `tests/`: test_rectify.py, TestVatRowExclusion в test_parse_flow.py
