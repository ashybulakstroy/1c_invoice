"""Build a self-contained HTML readiness report from local inventory."""
import html
import importlib.metadata
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from App.server_config import server_settings
SOURCE = ROOT.parent / "Prj_15_Torgsoft_Check_1C"
OUT = ROOT / "docs/reports/readiness_2026-10-27.html"

FOLDERS = [
    ("App/invoicing", "Адаптер проверенного чека, генерация и печать счёта", "Код предстоит перенести"),
    ("App/catalogs", "Адаптированные загрузчики каталогов 1С", "Код предстоит перенести"),
    ("data/in_data", "Фото для будущих пакетных проверок", "Пополняется при эксплуатации; старый корпус не требуется"),
    ("data/reference/torgsoft_ref", "Рабочий справочник Торгсофт", "Два XLSX уже скопированы"),
    ("data/reference/1c_ref", "Справочник номенклатуры 1С", "Нужна локальная копия из №15"),
    ("data/reference/User_Mapping", "Подтверждённые связи Торгсофт → 1С и предложения", "Нужен перенос с сохранением статусов"),
    ("data/reference/Training_Pair", "Проверенные пары: фото, счёт, expected.json", "Новые пары накапливаются при эксплуатации"),
    ("data/knowledge", "Связи OCR → Торгсофт текущего App", "Отдельно от связей с 1С"),
    ("data/invoices", "Предлагаемое общее хранилище итоговых документов", "Запись будет подключена при переносе"),
    ("data/training_jobs", "Предлагаемое хранилище задач обучения", "Обучение ещё не перенесено"),
    ("eval_outputs", "Артефакты будущих проверок", "Исторические данные не требуются"),
    ("experiments", "Необязательные экспериментальные инструменты", "Веб-приложение эти модули не использует"),
    ("Integration/1C", "Будущий клиент и контракт интеграции с 1С", "Последующий этап переноса"),
    ("docs/reports", "HTML-отчёты о состоянии проекта", "Этот отчёт"),
]

OPTIONAL_MODULES = ["experiments/" + name for name in (
    "local_row_split.py", "web_ocr_regression.py", "guarded_printed_grid.py", "ocr_failure_report.py")]


def esc(value):
    return html.escape(str(value))


def main():
    settings = server_settings()
    for relative, _, _ in FOLDERS:
        (ROOT / relative).mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(settings.browser_url + "/api/health", timeout=10) as response:
            health = json.load(response)
        server = bool(health.get("ok"))
    except (OSError, ValueError):
        server = False
    packages = {name: importlib.metadata.version(name) for name in (
        "rapidocr-onnxruntime", "onnxruntime", "openpyxl", "rapidfuzz", "pytest", "playwright")}
    browser_path = ROOT / "data/eval/startup_20261027/browser_results.json"
    browser = json.loads(browser_path.read_text(encoding="utf-8")) if browser_path.exists() else {}
    folder_rows = "".join(f"<tr><td><code>{esc(path)}/</code></td><td>{esc(purpose)}</td><td>{esc(status)}</td></tr>"
                          for path, purpose, status in FOLDERS)
    optional_missing = [path for path in OPTIONAL_MODULES if not (ROOT / path).is_file()]
    transfers = [
        ("Data/reference/1c_ref", "data/reference/1c_ref", "Скопировать .xls/.xlsx/.csv; каталог не задаёт цену продажи"),
        ("Data/invoice_issuer.json", "data/invoice_issuer.json", "Скопировать и проверить реквизиты поставщика"),
        ("Data/reference/User_Mapping", "data/reference/User_Mapping", "Сохранить подтверждённые альтернативы; top10 не подтверждать автоматически"),
    ]
    transfer_rows = "".join(
        f"<tr><td><code>{esc(source)}</code><br><span class='pill {'good' if (SOURCE/source).exists() else 'bad'}'>"
        f"{'Есть в №15' if (SOURCE/source).exists() else 'Не найдено'}</span></td>"
        f"<td><code>{esc(target)}</code></td><td>{esc(action)}</td></tr>"
        for source, target, action in transfers)
    package_rows = "".join(f"<span class='package'>{esc(k)} <b>{esc(v)}</b></span>" for k, v in packages.items())
    page = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Проект №16 — готовность к работе</title><style>
:root{--ink:#17253f;--muted:#64748b;--blue:#3159df;--line:#dce4f0;--bg:#f3f6fb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font:16px/1.65 'Segoe UI',Arial,sans-serif;color:var(--ink)}
main{max-width:1180px;margin:auto;padding:42px 26px 70px}header{background:#13264c;color:white;border-radius:22px;padding:34px 38px}
.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#adc3ff}h1{font-size:34px;line-height:1.2;margin:12px 0 18px}
header p{max-width:850px;color:#e0e9ff}h2{font-size:23px;margin:0 0 17px}h3{font-size:18px;margin:20px 0 8px}p{margin:10px 0}
a{color:var(--blue);text-underline-offset:3px}header a{color:#c7d7ff}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:22px 0}
.card,section{background:white;border:1px solid var(--line);border-radius:16px;padding:24px}.card strong{display:block;font-size:22px;margin:8px 0}
.card small,.muted{color:var(--muted)}section{margin:20px 0}.pill{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;border-radius:20px}
.good{background:#e5f6ed;color:#17623c}.warn{background:#fff2d5;color:#855615}.bad{background:#ffe8e5;color:#9b342a}
table{border-collapse:collapse;width:100%;font-size:14px}th{text-align:left;background:#f4f7fc;font-weight:600}th,td{padding:13px 14px;border-bottom:1px solid var(--line);vertical-align:top}
td:first-child{width:29%}.table-wrap{overflow-x:auto}code{font-family:Consolas,monospace;font-size:13px;overflow-wrap:anywhere}
ul,ol{padding-left:23px}li{margin:8px 0}.note{border-left:4px solid #e0a83b;background:#fff8e8;padding:15px 20px;margin:18px 0}
.flow{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.flow span{border:1px solid var(--line);padding:10px 14px;border-radius:9px;background:#f8faff}
.flow i{font-style:normal;color:#8ca0be}.package{display:inline-block;margin:5px;padding:5px 10px;background:#f1f5fb;border-radius:8px;font-size:13px}
details{margin:16px 0}summary{cursor:pointer;font-weight:600}footer{color:var(--muted);font-size:13px;padding:10px 4px}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}.button{border:1px solid #6e8bd0;border-radius:9px;padding:8px 15px;text-decoration:none}
@media(max-width:700px){main{padding:18px 12px}.cards{grid-template-columns:1fr}header{padding:24px}h1{font-size:27px}section{padding:18px}th,td{padding:9px}}
@media print{body{background:white}main{max-width:none;padding:0}header{background:white;color:#17253f;border:1px solid #dce4f0}header p,.eyebrow,header a{color:#17253f}.actions{display:none}section{break-inside:avoid}details{display:block}}
</style></head><body><main>
<header><div class="eyebrow">Проект №16 / состояние на 27 октября 2026</div>
<h1>От фотографии чека<br>до счёта на оплату</h1>
<p>Папки подготовлены. Распознавание и электронный чек работают на тестовом примере.
Для полного рабочего цикла необходимо перенести бизнес-логику счёта, данные 1С и завершить приёмку.</p>
<div class="actions"><a class="button" href="__WEBURL__" target="_blank">Открыть приложение</a>
<a class="button" href="../INVOICE_IMPORT_PLAN.md">Подробный план</a>
<a class="button" href="../WEB_VERIFICATION_2026-10-27.md">Протокол проверок</a></div></header>
<div class="cards"><div class="card"><span class="pill good">Окружение подготовлено</span><strong>Python __PYTHON__</strong><small>Локальный .venv, зависимости и OCR-модель установлены.</small></div>
<div class="card"><span class="pill __SERVERCLASS__">__SERVERSTATE__</span><strong>Порт __WEBPORT__</strong><small>HTTP health проверен при формировании отчёта; это снимок состояния, не мониторинг.</small></div>
<div class="card"><span class="pill warn">Следующий этап</span><strong>Генерация счёта</strong><small>Пока не перенесена. PDF счёта на оплату ещё не создаётся.</small></div></div>

<section><h2>01. Что уже работает</h2><ul>
<li>Основное приложение — <code>App/</code>. Python 3.14, RapidOCR/ONNX Runtime и кириллическая модель с проверенным SHA-256.</li>
<li>Два XLSX-справочника Торгсофт: при предыдущем запуске загружено <b>24 510</b> уникальных наименований.</li>
<li>На включённой фотографии распознаны <b>2 товара</b>; исходный и вычисленный итог совпали: <b>247 780,00 ₸</b>.</li>
<li>Проверены поток обновлений, сетка ячеек, сохранение итога, скачивание JSON/CSV/текста, восстановление страницы и мобильная ширина.</li>
<li>Исправлена ошибка обновления подписи исходного изображения. Последний браузерный прогон завершился без ошибок JavaScript и консоли.</li>
</ul><p class="muted">Результаты функциональной проверки — из сохранённого прогона 27.10.2026. Полный pytest при создании этого отчёта повторно не запускался.</p>
<div class="actions"><a href="../../data/eval/startup_20261027/browser_results.json">Результат браузерной проверки</a>
<a href="../../data/eval/startup_20261027/browser_receipt.png">Скриншот интерфейса</a></div>
<p>Проверка суммы не утверждает названия товаров автоматически: спорные строки остаются на проверке.</p></section>

<section><h2>02. Подготовленные папки</h2><p>Все перечисленные каталоги существуют. Рабочие файлы сохранены;
папки будущих модулей и данных созданы без фиктивной реализации.</p>
<div class="table-wrap"><table><thead><tr><th>Папка</th><th>Назначение</th><th>Что ещё требуется</th></tr></thead><tbody>__FOLDERS__</tbody></table></div>
<p class="muted">Текущие задания и исходные OCR-артефакты по-прежнему сохраняются в <code>web_outputs/&lt;job_id&gt;/</code>.
Новые папки <code>data/invoices</code> и <code>data/training_jobs</code> — подготовленная структура; путь записи подключается при реализации.</p></section>

<section><h2>03. Что нужно перенести из проекта №15</h2>
<p>Источник: <code>C:\Work\Projects\Prj_15_Torgsoft_Check_1C\</code>. Следующие данные найдены в источнике,
но в рамках подготовки папок не копировались и не объявляются подключёнными.</p>
<div class="table-wrap"><table><thead><tr><th>Источник в №15</th><th>Локальное назначение</th><th>Действие</th></tr></thead><tbody>__TRANSFERS__</tbody></table></div>
<div class="note"><b>Два разных вида связей:</b> OCR → Торгсофт остаётся в <code>data/knowledge</code>;
Торгсофт → 1С переносится отдельно. Предложения top10 не являются подтверждёнными правилами.</div></section>

<section><h2>04. Исторические тесты и experiments — не требования запуска</h2>
<p>Последний полный прогон: <b>121 passed · 12 failed · 2 ошибки сборки</b>. Падения связаны с отсутствующими фото,
сохранёнными артефактами и модулями унаследованных проверок. Это исторический результат, не перечень неисправностей веб-функций.</p>
<div class="note"><b>Уточнённое требование пользователя:</b> проект начинает работу без накопленных данных.
Старые фото, OCR-артефакты и история из 100 заданий не требуются для запуска. Проверенные примеры накапливаются при эксплуатации.</div>
<p>Обход локальной цепочки импортов от <code>App.web_server</code> и поиск по коду подтвердили:
ни один из четырёх модулей <code>experiments</code> не подключён к веб-серверу или конвейеру обработки.</p>
<div class="table-wrap"><table><thead><tr><th>Модуль</th><th>Ссылка в проекте</th><th>Для чего используется в тестах</th></tr></thead><tbody>
<tr><td><code>local_row_split.py</code></td><td><code>App/tests/test_local_row_split.py:5</code></td><td>Вызов экспериментального repair: разделение объединённых строк. В веб-конвейере не вызывается.</td></tr>
<tr><td><code>web_ocr_regression.py</code></td><td><code>App/tests/test_web_ocr_regression.py:5</code></td><td>latest_jobs/run: сравнение пробного алгоритма с сохранёнными заданиями, остановка при ухудшении.</td></tr>
<tr><td><code>guarded_printed_grid.py</code></td><td><code>App/tests/test_web_ocr_regression.py:130</code></td><td>matches_reviewed_reference: привязка ручного эталона к конкретному изображению и проверенному результату.</td></tr>
<tr><td><code>ocr_failure_report.py</code></td><td><code>App/tests/test_web_ocr_regression.py:179,189</code></td><td>write_failure_report: HTML-отчёт о провале экспериментальной проверки, открытие браузера по запросу.</td></tr>
</tbody></table></div>
<p><b>Без них не работают:</b> два тестовых модуля и перечисленные экспериментальные инструменты.
<b>От них не зависят:</b> загрузка фото, геометрия, OCR, создание электронного чека, его валидация, редактирование и выгрузки.</p>
<p>Назначение отсутствующих модулей установлено по вызывающим тестам; их реализации в проекте нет.
Текущая обработка использует <code>App.numeric_cell_split</code> и <code>App.quantity_cells</code>.
Восстанавливать эксперименты для эксплуатации не требуется. Генерация счёта ещё не перенесена по отдельным причинам, описанным далее.</p></section>

<section><h2>05. Что ещё реализовать для полного рабочего цикла</h2><ol>
<li><b>Адаптер подтверждённого чека.</b> Преобразовать <code>rows</code> в <code>items</code> генератора, сохранить идентичность строк,
текущие суммы, отдельный НДС, дату, номер, revision и происхождение значений. Вход — только после завершения проверки чека.</li>
<li><b>Бизнес-ядро счёта.</b> Адаптировать <code>invoice_generation.py</code>, <code>catalog_1c.py</code>,
<code>learned_mapping.py</code>, <code>transform_candidates.py</code> и необходимые вспомогательные функции в новые подпакеты №16.</li>
<li><b>Выбор товаров 1С.</b> Подключить локальный каталог, альтернативы, услуги, единицы и подтверждённые коэффициенты.
Неизвестные позиции должны быть видимы и блокировать готовность.</li>
<li><b>API и сохранение.</b> Реализовать предпросмотр, сохранение выбранных связей, модель документа, контроль revision/token,
отказ от устаревшего PDF и восстановление после перезапуска.</li>
<li><b>Интерфейс.</b> Добавить шаг «Счёт на оплату», редактирование шапки, выбор 1С, реквизиты, причины блокировки и кнопку PDF.</li>
<li><b>Печать PDF.</b> Перенести <code>invoice_presentation.py</code> и <code>invoice_pdf.py</code>; проверить кириллицу,
реквизиты, сумму прописью, таблицы и несколько страниц. Текущая печать чека не заменяет счёт.</li>
<li><b>Зависимости следующего этапа.</b> Проверить и установить совместимые с Python 3.14 версии
<code>reportlab</code>, <code>num2words</code>, <code>xlrd</code>, <code>pydantic</code>;
для последующего разбора счетов — <code>pypdf</code>. Сейчас это зависимости плана, не готовый модуль.</li>
<li><b>Сквозная приёмка.</b> Пройти реальные фото → подтверждение чека → трансформация → PDF/JSON;
проверить неизвестные товары, услуги, НДС, пересчёт количества, округления, отсутствующие реквизиты и устаревшие версии.</li>
</ol><div class="note">Суммы продажи берутся только из текущего чека и его проверенных правок.
Каталоги, остатки и прошлые счета не задают текущую цену. НДС не должен начисляться повторно.</div></section>

<section><h2>06. Критерии полной готовности</h2><div class="flow"><span>Фото</span><i>→</i><span>Чек №16</span><i>→</i><span>Проверка</span><i>→</i><span>Трансформация 1С</span><i>→</i><span>PDF счёта</span></div>
<ul><li>Все необходимые данные локальны; приложение работает без сервера и рабочих папок проекта №15.</li>
<li>Для каждого товара есть подтверждённая целевая номенклатура/услуга, единица и количество; сумма счёта равна проверенному чеку до тиына.</li>
<li>Непроверенный чек, конфликт связи или неактуальная версия не позволяют выдать финальный PDF.</li>
<li>Проверки действующих функций, API, браузера и визуальная проверка PDF пройдены на доступных примерах.
Корпус расширяется по мере эксплуатации; старый набор фото и 100 накопленных заданий не являются условием запуска.</li>
<li>Проверены реквизиты поставщика, сохранение/восстановление документов и повторный запуск приложения.
Для постоянной эксплуатации нужен согласованный автозапуск и резервное копирование.</li></ul>
<p>Полная готовность функций не означает 100% точности OCR на любых фотографиях.
Нечитаемые и неоднозначные данные требуют ручной проверки.</p></section>

<section><h2>07. Последующий импорт остальной логики</h2><p>В документации закреплено:
из №15 далее переносится вся остальная бизнес-логика, <b>кроме обработки и распознавания изображений,
создания электронного чека и его валидации</b>. Эти части остаются реализацией №16.</p>
<p>После приёмки счёта: обучение на парах и импорт PDF → история документов → обмен с 1С → сетевой доступ и остальные сценарии.
Обмен с реальной 1С потребует отдельной настройки базы, контракта, доступа и приёмки; он не нужен для локального PDF и сейчас не запускался.</p></section>

<section><h2>08. Окружение и повторная проверка</h2><p>__PACKAGES__</p>
<p><code>.venv\Scripts\python.exe -X utf8 -m App.web_server</code></p>
<p><code>.venv\Scripts\python.exe -X utf8 tools/check_app_browser.py</code></p>
<p><code>.venv\Scripts\python.exe -X utf8 -m pytest App/tests -q --continue-on-collection-errors</code></p>
<p class="muted">Старое окружение сохранено в <code>.venv-py312-backup</code>.
Отчёт формируется командой <code>.venv\Scripts\python.exe -X utf8 tools/build_readiness_report.py</code>.
Исторические проверки со старыми данными и experiments учитываются отдельно от проверок действующего веб-приложения.</p></section>
<footer>Локальный отчёт проекта №16 · 27.10.2026 · Папки созданы, генерация счёта ещё не перенесена.</footer>
</main></body></html>"""
    substitutions = {
        "__PYTHON__": esc(sys.version.split()[0]),
        "__WEBURL__": esc(settings.browser_url), "__WEBPORT__": str(settings.port),
        "__SERVERCLASS__": "good" if server else "bad",
        "__SERVERSTATE__": "Сервер отвечает" if server else "Сервер не отвечает",
        "__FOLDERS__": folder_rows, "__TRANSFERS__": transfer_rows,
        "__PACKAGES__": package_rows,
    }
    for key, value in substitutions.items():
        page = page.replace(key, value)
    OUT.write_text(page, encoding="utf-8")
    manifest = dict(date="2026-10-27", server_ok=server, python=sys.version.split()[0],
                    folders=[dict(path=p, purpose=purpose, status=status, exists=(ROOT/p).is_dir())
                             for p, purpose, status in FOLDERS],
                    historical_data_required=False, optional_missing_test_modules=optional_missing, packages=packages,
                    previous_browser_job=browser.get("job_id"))
    OUT.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(report=str(OUT), folders=len(FOLDERS), historical_data_required=False, server_ok=server), ensure_ascii=False))


if __name__ == "__main__":
    main()
