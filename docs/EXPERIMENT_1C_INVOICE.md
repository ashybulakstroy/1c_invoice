# Эксперимент 1С-инвойсинг: этапы, решения, результаты

Дата начала: 29.10.2026. Пакет эксперимента: `R:/Experiment_Torgsoft_1C_Transformation_Invoice/`
(инструкции `AGENT_INSTRUCTIONS.md`, `IMPLEMENTATION_PLAN.md`; донор — `donor_sources/App/`).
Приёмник: локальный `C:/Work/Projects/Prj_16_OCR` (Python 3.14, `.venv`, сервер на `0.0.0.0:8016`).
Согласующий план: `docs/INVOICE_IMPORT_PLAN.md` (маршруты и адаптер описаны там и приняты).

## 1. Исходная точка

- Бекап проекта: `R:/Backups/Prj_16_OCR_backup_20261029_pre_1c_invoice` (1.99 ГБ, 7777 файлов, robocopy — без ошибок).
- Файлы, перенесённые из №15 накануне: `Data/invoice_issuer.json`, `Data/network_api_key.txt`.
- Справочники уже на месте: `Data/reference/1c_ref` (xls), `Data/reference/TorgSoft_ref` (csv+2 xlsx),
  `Data/reference/User_Mapping` (`Torgsoft_1C_mapping.json`, 20 МБ `torgsoft_1c_transform_top10.json`),
  `Data/reference/Training_Pair` (12 кейсов + expected.json).
- Важное отличие: СПРАВОЧНИК 1С — файл `.xls` (старый формат BIFF) → нужен `xlrd`; справочники Торгсофта `.xlsx`+csv → уже читаются `openpyxl`.

## 2. Инвентаризация приёмника (ключевое)

- Сервер: stdlib `http.server.ThreadingHTTPServer` — `App/web_server.py::create_server/main`;
  routes в if-цепочках `do_GET` (201–235) и `do_POST` (266–310); статики — белый список из `STATIC = App/web`.
- Модель чека — plain-dict, без классов:
  сборка `App/web_pipeline.py::_process_attempt` (schema `torgsoft-review-1.0`);
  обновление/валидация `App/receipt_editing.py::update_receipt` — `revision`, `audit_log`, `finalized`,
  `calculation{status, validation_status, vat{expected_tax, rate_percent...}, computed_total, expected_total, difference, ...}`;
  строка строится в `App/ocr_catalog_eval.py::parse_rows`: `row` (int, 1-based, стабильный id),
  `name_raw/name`, `article`, `catalog_key`, `kind` (`product|service|tax|total|header`),
  `line_total`, `match{status, best, top_matches, source}`, `name_confirmed`, `needs_review`;
  НДС — **отдельными строками `kind="tax"`**, per-line VAT поля нет; проверка — `App/receipt_math.py::verify_vat`.
- Задания: `JobStore` (в памяти) + файлы `web_outputs/{job_id}/…`, `state.json`, восстановление 100 последних;
  фоновый пул `ThreadPoolExecutor(max_workers=1)`; события в SSE через `job.publish/phase`.
- Точка выдачи готового чека: `POST /api/jobs/{id}/edits` с `finalize` → `App/receipt_editing.py::apply_edit`
  (`finalized=True`, `finalized_at`) → `save_receipt` (`receipt.json.tmp`→атомарный `.json`, `receipt.csv`);
  экспорт: `GET /api/jobs/{id}/files/receipt.json|receipt.csv` (whitelist `DOWNLOADS`).
  Это и есть вход нового слоя 1С-маппинга и счёта.
- Обучение OCR→Торгсофт: `App/manual_mappings.py` + `Data/knowledge/manual_mappings.json`
  (атомарная запись, RLock) — отдельное хранилище от Торгсофт→1С (требование плана, не смешивать).
- Горячий перегруз каталога: `ReceiptPipeline::ensure_catalog` по подписи файлов.
- Фронт: `App/web/{index.html, app.js (829 стр.), styles.css, editing.css, ocr_activity.*}` — без бандлера;
  редактор строк уже показывает альтернативы (`showCandidates/selectCandidate`, `/api/catalog` top-8) —
  образец UX для кандидатов 1С.

## 3. Карта «донор → приёмник»

| Донор-файл | Роль | Действие интеграции |
|---|---|---|
| `catalog_1c.py` | индекс 1С из всех листов xls/xlsx/csv | адаптировать → `App/invoicing/` (новый подпакет; возможна замена xlrd-логики чтения .xls); импорты `App.user_mapping` переписать |
| `user_mapping.py`, `learned_mapping.py` | подтверждённые правила + накопленное обучение | адаптировать → `App/invoicing/`; приоритет: подтверждённое > кандидаты |
| `transform_candidates.py` | до 10 кандидатов, статус `not_confirmed` | адаптировать; pydantic-модели; файл‑хранилище уже есть (20 МБ) |
| `receipt_names.py`, `torgsoft_reference.py` | имена Торгсофта, прайс-справочник | адаптировать частично; не допустить, чтобы raw OCR сильнее подтверждённого имени |
| `invoice_generation.py` | строки счёта, Decimal/НДС, флаги | адаптировать → `App/invoicing/`; НДС из строк `kind="tax"`; не начислять 16% сверху |
| `invoice_presentation.py`, `invoice_pdf.py` | эталонный вид, PDF (reportlab), сумма прописью (num2words) | адаптировать; предпросмотр == PDF |
| `document_edits.py`, `task_store.py` | поздние правки документа, хранение задач | реализовать по мере Этапов 3–4 на механике №16 (revision/audit_log), не вторую валидацию |
| `exchange.py`, `network_access.py`, `training_*`, `pdf_invoice.py` | обмен с 1С, обучение, разбор PDF | только изучение (не переносить в первый перенос; контракты на будущее) |
| `web.py`, `static/*` | примеры API/UX | НЕ копировать целиком; идеи выбора альтернатив и предпросмотра — в новый блок `App/web` |

Решения: новые модули не конфликтуют по именам с существующими файлами `App/`
(нет `catalog_1c.py`, `invoice_*.py`, `transform_*.py`, `user_mapping.py` в приёмнике);
размещать в подпакете `App/invoicing/` (переписать импорты донора), `App/` целиком не трогать.

## 4. Зависимости

- В `.venv` уже есть: rapidfuzz, openpyxl, numpy, opencv, pillow, python-dotenv, pytest, playwright.
- Нужно добавить (после проверки на Python 3.14): `pydantic` (модели донора),
  `xlrd` (чтение .xls справочника 1С), `reportlab` (PDF), `num2words` (сумма прописью), `pypdf` (позже, разбор PDF).
- `fastapi` требуется только донорским тестам (`from fastapi.testclient import TestClient`) — донорский `web.py/exchange.py`
  целиком не переносятся; решение по тестовому каркасу (адаптировать тесты под собственный сервер или добавить
  fastapi для тестов) принять на Этапе 7 и зафиксировать в отчёте.

## 5. Baseline тестов (коммит-точка)

Команда: `.venv/Scripts/python.exe -X utf8 -m pytest App/tests -q` (из корня проекта).

Результат: **172 теста: 160 passed, 12 failed** (12.5 с).

- Все 12 падений совпадают один-в-один с эталоном master-import
  (`Data/eval/master_import_20261029/pytest.log`): у тестов геометрии/границ
  `test_geometry`, `test_geometry_review`, `test_ocr_catalog_eval::test_real_tax_cell_boundary`,
  `test_table_boundary` отсутствуют fixture-фото 2026‑10‑22…25 в `data/in_data` (`cv2.imread` → None).
  Это известное наследованное состояние, к OCR-механике не относится и не является регрессией.
- Легаси `tests/` (Фаза 1, пакет `receipts_ocr` не существует) в baseline не включаются
  (AGENTS.md: не являются требованием запуска).
- Браузерные проверки `App/tests/browser_*.py` — не pytest; требуют запущенного сервера, отдельно.

Новый функционал не добавляет тестов OCR; любое влияние будут отражаться сравнением с этим baseline.

## 6. Классификация воздействия на OCR (требование AGENT_INSTRUCTIONS §34–39)

- Этапы 1–2 (инвоисинг-подпакет, каталог, маппинг, генерация, представление, PDF): **изолированы после
  finalized-снимка**; синтетических тестов достаточно.
- Этапы 3–5 (правки `App/web_server.py` — новые ветки в `do_GET/do_POST`, новые файлы статики в белом списке,
  фронтовые правки) формально могут косвенно затронуть OCR-контур: сервер и пайплайн разделены, но файл общий.
  По правилу «при сомнении — потенциальное воздействие» на Этапе 7 запланирована регрессия на реальных
  фото чеков (сравнение с эталонами, без перезаписи эталонов), независимо от классификации отдельных правок.

## 7. Риски / несовместимости, закладываемые в работу

1. `.xls` справочника 1С — xlrd; проверить читаемость всех вкладок и кодировок до написания индексатора.
2. Донор статикой лежит в `App/static/`, приёмник в `App/web/`; файлы фронтенда донора
   (`index.html`, `app.js`, `styles.css` clashed by name) копировать нельзя — только фрагменты логики.
3. У строк приёмника нет своего stab­ильного UUID — в адаптере `row_id` = `rows[].row` (+`job_id`+`revision`).
4. НДС: в чеке отдельные строки `kind="tax"`; генератору нельзя суммировать их ещё раз как позиции и
   нельзя автоматически доначислять 16%.
5. Цены/суммы — только из проверенного чека; остатки 1С — сортировка/предупреждение, не тождество товара.
6. Донорские хранилища (`Data/reference/User_Mapping/...`) уже наполнены реальными данными — при адаптации
   не переписывать их формат; версия/резерв перед первой записью.
7. Путь OCR-артефактов и `DOWNLOADS`-whitelist и статик-whitelist в сервере — точечные расширения, без переименований.

## 8. Точки возврата (rollback)

- Полная копия: `R:/Backups/Prj_16_OCR_backup_20261029_pre_1c_invoice/` — восстановление = robocopy /MIR назад
  или вручную перезаписать `App/`, `Data/`, `docs/`.
- До Этапа 3 правки веб-слоя — отдельная резервная копия изменяемых файлов внутри проекта (`docs/`+`App/` 
  снапшот в `Data/eval/`, по правилу AGENT_INSTRUCTIONS §45) — сделать перед каждым изменением файлов приёмника.

---

# Этап 1 — контракт и адаптер проверенного чека (выполнен 29.10.2026)

## Дополнительно к исходной точке

- В `.venv` установлены и проверены на Python 3.14: `pydantic 2.14.1` (ядро pydantic-core 2.50.1),
  `xlrd 2.0.2`, `reportlab 5.1.0`, `num2words 0.5.14`, `pypdf 6.21.4`. Всё добавлено в
  `requirements-app.txt` с версиями. `fastapi` осознанно НЕ установлен (донорский `web.py` не переносится).
- Проверен входной контракт донорского генератора `donor_sources/App/invoice_generation.py::build_generation`:
  вход — объект `{"items":[{row_id,name,quantity,price,...}], "vat_amount", "total", "date", "order_number",
  "warnings"}`; имя товара через `torgsoft_name()` предпочитает подтверждённое значение при `edited=True`.
  Адаптер сразу выдаёт эту форму, чтобы Этап 4 подключил донорскую логику без повторной валидации.

## Что создано (только новые файлы; OCR не тронут)

| Файл | Содержание |
|---|---|
| `App/invoicing/__init__.py` | границы пакета: чтение снимка, без второго распознавания/валидации |
| `App/invoicing/receipt_adapter.py` | pydantic-модели `ReceiptLine`/`VatSummary`/`ReceiptSnapshot`; функции `snapshot_from_receipt`, `snapshot_from_directory`, `to_generation_source`, `relation_warnings`; детерминированный SHA-256 `fingerprint` снимка |
| `App/tests/test_invoicing_receipt_adapter.py` | 11 синтетических тестов контракта |

## Семантика адаптера (ключевые решения)

1. `lines` — только `kind ∈ {product, service}`; `tax` → сводка `vat` (суммы строк НДС), `total/header` — структурные, исключаются.
   Неизвестные типы строк не молча: исключаются и попадают в `warnings`.
2. Название: `name` — текущее подтверждённое значение чека; `ocr_name` (`name_raw`) сохраняется отдельно как доказательство;
   `edited_name = name_origin != "ocr"` → донорский `torgsoft_name` вернёт подтверждённое имя (правка плана §4).
3. Числа: `quantity/price/line_amount` — `Decimal` через собственный `App.receipt_editing.parse_number`
   (полная совместимость правил приёмника: пробелы, валюта-суффиксы, KZT); сырые строки хранятся отдельно
   (`quantity_raw` = нетронутое OCR-значение `quantity_raw`, а не отредактированное `quantity`).
4. Расхождения не исправляются: `количество × цена != line_amount` и нераспознанные числа → строки остаются видимыми
   с флагами (`invalid_fields`, `needs_review`) и явными предупреждениями; снимок строится и без finalize и
   без `calculation.status == "match"` (для предпросмотра), но сохраняет `finalized`/`validation_status` для контроля готовности счёта.
5. Дубликаты `rows[].row` и отсутствие `job_id` — ошибка сборки (ValueError), не тихий пропуск;
   пустой/отсутствующий `rows` — ошибка.
6. `fingerprint` — sha256 канонических полей снимка (job_id, revision, шапка, статусы, строки с сырыми и
   Decimal-значениями); не зависит от порядка подачи и предупреждений; меняется при любой содержательной правке.
7. `to_generation_source` выдаёт донорский словарь, добавляя только доп. поля (`source_job_id`,
   `source_revision`, `source_fingerprint`, `vat_status`, подмножества и флаги строк) — донор их игнорирует по `.get`.

## Результаты

- `pytest App/tests/test_invoicing_receipt_adapter.py` → **11 passed**.
- Полный регресс: `pytest App/tests -q` → **171 passed, 12 failed** — те же 12 падений baseline
  (отсутствие fixture-фото в `data/in_data`), новых падений нет, OCR-контур не изменён.
- Классификация по AGENT_INSTRUCTIONS §34: Этап 1 изолирован после проверенного чека — синтетических тестов
  достаточно; регрессия на реальных фото не требуется (и будет повторена на Этапе 7 из-за веб-правок Этапов 3–5).

## Следующие шаги (Этап 2)

1. Проверить читаемость всех вкладок `Data/reference/1c_ref/*.xls` через xlrd; свести статьи/наименования
   с донорским `catalog_1c.py`; индекс: коды/единицы/остатки/склад/дата среза — раздельно, «не выдумывать».
2. Адаптировать `catalog_1c.py` → `App/invoicing/` (импорты донора заменить), `transform_candidates.py`
   (pydantic уже есть; 20 МБ top10-файл уже на месте и не менять формат), подготовить `/api/catalog-1c`.

---

# Этап 2 — каталог 1С и рекомендации-кандидаты (выполнен 29.10.2026)

## Проверка реальных данных

- `Data/reference/1c_ref/Склад Алатау на 16.10.2026.xls` (xlrd, 3 листа «Товары/Услуги/Производство», 972 КБ):
  шапки многострочные (названия на строке 8, подшапка остатков на строке 9), «Итого»-строки, двойные шапки
  с закреплёнными областями. Код/артикул — «Код / Артикул», Ед.изм., под «Конечный остаток»: Учетная цена,
  Количество, Сумма. Наименования файлов содержат склад и дату среза.
- Файл предложений `torgsoft_1c_transform_top10.json`: 24 522 строк, 5 185 с кандидатами, 0 битых записей,
  формат 1.0 (pydantic `ProposalRow`).

## Что создано (новые файлы)

| Файл | Содержание |
|---|---|
| `App/invoicing/user_mapping.py` | OCR→Торгсофт-справочник донора (`OCR_Torgsoft_mapping.txt`), `normalize_mapping_key` — общая политика ключей |
| `App/invoicing/catalog_1c.py` | адаптированный донорский индекс: все листы; развёртка двойных шапок; коды/единицы/услуги раздельно; к карточке добавлены `stock_quantity/stock_amount/accounting_price/account_code` (или None=unknown) и `warehouse/snapshot_date` из имени файла; поиск по коду 100% и fuzzy-поиск с числовым покрытием |
| `App/invoicing/receipt_names.py` | донорское правило имени: подтверждённое > OCR |
| `App/invoicing/transform_candidates.py` | кандидаты 1.0: ≤10, rank, код/название/единица/остаток/дата, `not_confirmed`; join со каталогом по коду; диагностика «карточка изменилась»; не подтверждает автоматически |

## Ключевые решения

1. Остаток — добавленная информация (AGENT_INSTRUCTIONS §24), только для сортировки/предупреждений;
   цена продажи остаткам не назначается, «Сумма По убыванию»-строки шапки не попадают в товар.
2. Склад/дата среза берутся ТОЛЬКО из имени файла; нет — None (не «выдумывать»).
3. Одноимённые товары с разными кодами остаются отдельными карточками; дубликаты кодов между листами
   → ошибка неоднозначности в индексе (снаружи видна в `errors`).
4. Служебный лист «Услуги» → `service=True`, единица «усл»; «Производство» сохраняет код/единицу/остаток.
5. `TORGSOFT_TRANSFORM_CANDIDATES` env-путь и кэш по mtime/размеру — как у донора; запись в top10-файл
   из Этапа 2 не делается (кандидаты только читаются).

## Результаты

- Реальный файл: **Товары 3701 / Производство 19 / Услуги 11 = 3731 карточка, errors == []**, код «00000019603»
  → Бетон М350 (м3, остаток 630, дата 16.10.2026, склад «Склад Алатау»); строка «Строительный карандаш»
  → остаток None.
- Тесты: `test_invoicing_catalog_1c.py` → **11 passed**; полный регресс — **182 passed / те же 12 known-failures**.
- OCR не затронут → синтетических тестов достаточно (AGENT_INSTRUCTIONS §34–36).

---

# Этап 3 — подтверждённый маппинг и учебные правила (выполнен 29.10.2026)

## Проверка реальных данных

- `Data/reference/User_Mapping/Torgsoft_1C_mapping.json` — хранилище подтверждённых правил донора
  (5 записей: ключи по нормализованному имени Торгсофт и по `card:<sha256>` от [database_id, identity]);
  значение: `{catalog_id, name, unit, quantity_factor, service [, service_quantity, alternatives…]}`.
- `Data/reference/Training_Pair/case_*/expected.json` — 12 кейсов, все `training_ready: true`,
  со связями `links` (predzakaz_row → invoice_row).

## Что создано (новые файлы)

| Файл | Содержание |
|---|---|
| `App/invoicing/learned_mapping.py` | адаптация донора: `prepare_training_pair` (допуск обучения: арифметика пары, НДС ±0.99, однозначные связи строк по суммам); `mapping_rules` (55 правил из 12 кейсов, конфликт-детект), `source_rule`, `apply_training_pairs` (коэффициенты количества / service-режим), `training_alternatives`, `vat_matches` |
| `App/invoicing/invoice_generation.py` | подтверждение выбора: `confirmed_record` (карточный ключ → по имени), `remember_selections` (+ ВЕРСИОНИРОВАННЫЙ бэкап `history/Torgsoft_1C_mapping_*.json`, хранить 5), `confirmed_candidates` |

## Ключевые решения

1. `VAT_TOLERANCE = 0.99` остаётся ТОЛЬКО внутри учебных пар и сопоставления гипотетических сумм;
   строгая валидация электронного чека №16 (адаптер Этапа 1) — точная, допуском не ослабляется.
2. `Decimal.CENT` не существует (`from decimal import CENT` из донора невалидно) → `CENT = Decimal("0.01")`.
3. Правила по имени без `catalog_id` и не-service мертвы в строках счёта (`_current_rule` → None) —
   донорская семантика сохранена: remember с карточным ключом/каталогом обязателен для товаров.
4. Бэкап знаний пишется перед КАЖДОЙ перезаписью `Torgsoft_1C_mapping.json` (tmp+replace, хранить 5).
5. `database_id`: env `TORGSOFT_CATALOG_DATABASE_ID` → «local» по умолчанию; реальная 1С не подключается.

## Результаты

- Реальные данные: **55 правил, 0 конфликтов**; `invoice_catalog()` → 32 карточки;
  `suggest_catalog("Бетон М350")` → корректная карточка, `suggest_catalog("Доставка")` → услуга.
- Тесты: `test_invoicing_learned_mapping.py` → **7 passed** (синтетика + реальные 12 кейсов).
- Полный регресс после этапа: без падений сверх 12 известных (см. Этап 4).

---

# Этап 4 — формирование счёта, печатная форма и PDF (выполнен 29.10.2026)

## Что создано (новые файлы)

| Файл | Содержание |
|---|---|
| `App/invoicing/invoice_presentation.py` | печатные поля: даты словами, `print_number` (пробел-разряды, запятая), суммы прописью («…теңге … тиын») |
| `App/invoicing/invoice_pdf.py` | донорский рендер A4 (reportlab, Arial из C:/Windows/Fonts, кириллица), `render_invoice_pdf(document) → bytes` |
| `App/invoicing/invoice_generation.py` | `build_generation(receipt, selections, suggest, database_id)` — полная сборка: learned/manual/remembered/unmatched + предупреждения (никогда не скрывать неподтверждённые строки); `source_fingerprint` (имя+количество+цена); `transformed_numbers` (услуги: количество↔цена при фикс. сумме); `invoice_document` (номер `OCR-<order>`, дата, реквизиты `Data/invoice_issuer.json`, errors → ready=False, детерминированный token-SHA256) |
| `tools/copy_invoicing_donor.py` | одноразовый перенос с подсчётом замен (контроль импортов донора) |

## Ключевые решения

1. `ROOT = parents[2]` (App/invoicing/*), импорты → `App.invoicing.*`; ISSUER/KNOWLEDGE резолвятся.
2. Цены/суммы — только из проверенного снимка чека: НДС распределяется по долям нетто в тиын;
   расхождение > допуска → ПРЕДУПРЕЖДЕНИЕ «Арифметика исходного чека не сходится», не автоправка.
3. `selection.source_fingerprint` обязателен: изменённая строка чека никогда не «заглатывает» старый выбор
   (warning «Повторно проверьте связь после правки чека»).
4. Противоречивые выборы в одном батче → ValueError (в т.ч. разные коэффициенты одной карточки).
5. `document_edits.py` / `task_store.py` донора перенесены НЕ будут — они про хранилище задач донора,
   в №16 ответственен `App.task_store` (UI/API Этап 5 берёт оттуда).

## Результаты

- Тесты: `test_invoicing_invoice_generation.py` → **11 passed**: unmatched/manual/remembered-строки,
  защита стейл-фингерпринта, история бэкапов (≤5, «разные связи» → отказ), invoice_document
  (готовность, `OCR-1234`, стабильный token), печатные форматы (!,), PDF одна страница и читается pypdf.
- Полный регресс: **200 passed / те же 12 known-failures** (`test_table_boundary` — недостающие
  fixture-фото `Data/in_data`, к OCR-конвейеру не относятся).

---

# Этап 5 — API счёта и панель оператора (выполнен 29.10.2026)

## Что создано / изменено

| Файл | Содержание |
|---|---|
| `App/invoicing/invoice_service.py` | НОВЫЙ: сервис счёта для веб-сервера. `invoice_model` (снимок → источник → build_generation → document → кандидаты по строкам), `save_selections/load_selections` (атомарно, `invoice_state.json`, schema 1, под `job.condition` + lock), `render_invoice` (PDF только при совпадении revision+token и готовности), `search_catalog_1c` |
| `App/web_server.py` | Минимальные правки: импорт сервиса + `ValidationError`; статики `/invoice.js`, `/invoice.css`; `GET /api/catalog-1c`; расширенные маршруты `GET /api/jobs/{id}( /events /files/… /invoice /invoice.pdf)` и `POST /api/jobs/{id}/invoice/(preview\|selections)` → `handle_invoice_request`; неожиданные исключения → 500-JSON (не обрыв соединения) |
| `App/web/index.html` | `<link>/invoice.css`, `<script>/invoice.js` + секция «03 / СЧЁТ 1С» |
| `App/web/invoice.js`, `App/web/invoice.css` | НОВЫЕ: панель оператора — строки чека, до 10 кандидатов (предложения/подтверждённые ранее/поиск по справочнику), явный выбор + количество 1С, «Предпросмотр» (без записи) и «Сохранить связи», список причин неготовности, PDF-ссылка с revision+token |

## Ключевые решения

1. **НДС «в том числе»**: донор начисляет НДС сверху строк; в №16 итог чека уже включает НДС →
   сервис передаёт в `build_generation` `vat_amount=None` (суммы строк = проверенным суммам чека),
   печатный НДС (tax_subtotal чека) показывается строкой «В том числе НДС»; сверху НДС не начисляется.
2. **Точные суммы строк** `_exact_amounts`: каждая строка счёта сверяется с проверенной суммой
   строки чека; расхождение → блокирующая причина + точная сумма (никогда молчаливая правка).
3. Ревизия = SHA256(token документа + сигнатура файлов каталога + сигнатура реквизитов);
   правка чека через `_edits` сбрасывает finalized → счёт блокируется, старый PDF → 409.
4. Выбор оператора строго через pydantic (`quantity` > 0, StrictStr); preview записи не делает;
   неизвестные row_id дропаются молча (модель остаётся видимой с причинами).
5. Кандидаты (предложения/подтверждённые ранее) НИКОГДА не подтверждаются сами — только клик оператора.

## Результаты

- `test_invoicing_invoice_api.py` → **6 passed**: находка по коду («Бетон М350»), 409 до готовности
  распознавания, preview не персистит, selections персистят + PDF (200, %PDF; token-only → 409,
  неверный token → 409), 409 + новая ревизия после правки чека, 400 при quantity=«0».
- Полный регресс → **206 passed / те же 12 known-failures**.
- `invoice.js` проверен синтаксически (node v24.14.1).

---

# Этап 6 — оформление документа (выполнен 29.10.2026, вместе с этапом 4)

- Донорские `invoice_presentation.py` / `invoice_pdf.py` адаптированы на Этапе 4; здесь добавлен
  приёмочный тест `test_pdf_multi_page_and_long_cyrillic_names`: 28 строк с длинными кириллическими
  названиями → ≥2 страницы A4, «Всего наименований 28», итог формата донора («…теңге … тиын»).
- «В том числе НДС» берётся ИЗ снятого чека (tax_subtotal); ничего не доначисляется и не пересчитывается.
- `test_invoicing_invoice_generation.py` → **12 passed**.

---

# Этап 7 — реальная регрессия и сдача (выполнен 29.10.2026)

## Реальное фото через полный пайплайн

Скрипт `tools/regress_real_photo_invoicing.py` (фото legacy-задания `771f241f…`, 1717 КБ,
эфемерный порт, полный OCR-пайплайн; артефакты — `web_outputs/regress_real_photo_check/`):

- OCR: **status done за 13,1 с; 12 строк / 11 items; validation=match** — идентично прошлому
  legacy-прогону этого фото: изменения endpoints/статики на распознавание не повлияли.
- `GET /invoice` → 200: total `230214.00`, кандидаты по 11 строкам (8 строк с предложениями,
  4 без — заполняются ручным поиском), 14 блокирующих причин (не финализирован +
  «Выберите номенклатуру 1С»), PDF корректно запрещён до подтверждения.
- `GET /api/catalog-1c?q=00000019603` → 200, «Бетон М350 (В25…)»; `/invoice.js`, `/invoice.css` → 200.
- Итог чека `230 214,00T` распознан с валютой; суммы сведены без расхождений.

## Найденное и исправленное

1. **Реальные цены вида «36530T»**: `to_generation_source` отдавал сырые строки → падение
   `Decimal` в донорской математике (500 на реальном фото). Фикс: в источник генерации идут
   канонические числа (`str(line.quantity/price/amount)`), сырые строки остаются fallback'ом;
   добавлен тест `test_generation_source_tolerates_real_tenge_strings` (10 530,00T / 36530T).
2. Обрыв соединения при непредвиденной ошибке → все invoice-обработчики возвращают 500-JSON.

## Итог

- Полный регресс: **207 passed / те же 12 known-failures** (все 12 — недостающие fixture-фото
  `data/in_data`/`eval_outputs`, к OCR-конвейеру не относятся).
- Откат всех изменений: `R:/Backups/Prj_16_OCR_backup_20261029_pre_1c_invoice/` (сделан до старта).
- В работающем сервере `0.0.0.0:8016` (PID 1532) код загружен ДО этих правок — для панели
  «03 / СЧЁТ 1С» нужен перезапуск `.venv/Scripts/python.exe -X utf8 -m App.web_server`
  (пользователь уведомлён; без спроса не перезапускается).
