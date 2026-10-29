"""Read-only A/B test on the two newly supplied receipt photos."""
import hashlib
import html
import json
import sys
import traceback
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare_master_geometry import candidate_module
from App import contour_unwarp, receipt_rectification
from App.receipt_editing import parse_number
from App.web_pipeline import ReceiptPipeline
from App.web_server import Job

OUT = ROOT/'data/eval/new_real_receipts_20261029'
CASES = [
    dict(file='WhatsApp Image 2026-10-26 at 09.02.00.jpeg', number='2142736994',
         quantity='3', price='1000', vat='480.00', total='3480.00', label='Скотч Прозрачный 60/250'),
    dict(file='WhatsApp Image 2026-10-26 at 11.09.07.jpeg', number='2142737199',
         quantity='1', price='63090', vat='10094.00', total='73184.00', label='Насос глубинный 71 мм 1800W T00708 TEXA'),
]


def write_summary(summary):
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')


def compare_runs(summary):
    for case in summary['cases']:
        runs={run['variant']:run for run in case['runs']}
        master,candidate=runs.get('master',{}),runs.get('candidate',{})
        case['no_new_failed_checks']=bool(master.get('checks') and candidate.get('checks')) and all(
            not passed or candidate['checks'].get(key,False) for key,passed in master.get('checks',{}).items())
        directory=OUT/case['expected']['number']
        paths=[directory/variant/'rectified.png' for variant in ['master','candidate']]
        case['rectified_images_identical']=all(path.exists() for path in paths) and paths[0].read_bytes()==paths[1].read_bytes()
    summary['no_new_failed_checks']=all(case['no_new_failed_checks'] for case in summary['cases'])


def render(summary):
    cards=[]
    labels=dict(product_count='Число товаров',tax_rows='Отдельная строка НДС',quantity='Количество',
                price='Цена',vat='Сумма НДС',computed_total='Сумма по строкам',printed_total='Итог с фото',
                validation='Завершённая проверка суммы и НДС',order_number='Номер заказа',date='Дата')
    for case in summary['cases']:
        columns=[]
        for run in case['runs']:
            if run.get('error'):
                columns.append(f"<div><h3>{run['variant']} — ERROR</h3><pre>{html.escape(run['error'])}</pre></div>")
                continue
            check_rows=''.join(f"<li>{html.escape(labels.get(key,key))}: <b>{'PASS' if passed else 'FAIL'}</b></li>" for key,passed in run['checks'].items())
            product_text='; '.join(row.get('name_raw','') for row in run['products'])
            values='; '.join(f"Количество: {row.get('quantity') or 'не прочитано'}; цена: {row.get('price') or 'не прочитана'}" for row in run['products'])
            columns.append(f"<div><h3>{run['variant']} — {'PASS' if run['passed'] else 'FAIL'}</h3>"
                           f"<p>OCR: {html.escape(product_text)}</p>"
                           f"<p>{html.escape(values)}. Номер заказа: {html.escape(run.get('order_number') or 'не прочитан')}.</p>"
                           f"<p>По распознанным строкам: {html.escape(str(run['calculation']['computed_total']))}; итог с фото: {html.escape(str(run['calculation']['expected_total']))}; НДС: {html.escape(str(run['calculation']['tax_subtotal']))}</p>"
                           f"<ul>{check_rows}</ul><img src='../../data/eval/new_real_receipts_20261029/{case['expected']['number']}/{run['variant']}/rectified.png'></div>")
        cards.append(f"<section><h2>Чек №{case['expected']['number']}</h2><p>{html.escape(case['file'])}</p>"
                     f"<p>Эталон прочитан с фото: {html.escape(case['expected']['label'])}; "
                     f"{case['expected']['quantity']} × {case['expected']['price']}; НДС {case['expected']['vat']}; итог {case['expected']['total']}.</p>"
                     f"<p>Новых проваленных проверок относительно мастера: {'нет' if case.get('no_new_failed_checks') else 'есть'}. "
                     f"Выпрямленные изображения побайтово совпадают: {'да' if case.get('rectified_images_identical') else 'нет'}.</p>"
                     "<div class='grid'>"+''.join(columns)+"</div></section>")
    page="""<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Два новых реальных чека · A/B проверка</title><style>body{font:16px/1.65 Segoe UI,sans-serif;background:#f3f6fa;color:#182f4e;margin:0}main{max-width:1150px;margin:auto;padding:24px}section,header{padding:24px;border:1px solid #dce5f1;background:white;border-radius:16px;margin-bottom:20px}header{background:#172f55;color:white}.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}img{width:100%}p,pre{overflow-wrap:anywhere}pre{white-space:pre-wrap}a{color:#2855ca}@media(max-width:650px){.grid{grid-template-columns:1fr}}</style><main>
<header><h1>Новые реальные чеки: мастер и кандидат</h1><p>29.10.2026 · Полный OCR-пайплайн, без подстановки эталонных значений</p></header>
<section><h2>Методика</h2><p>Использованы два новых фото из data/in_data. Эталонные количество, цена, НДС, итог и номер заказа прочитаны с фотографий до запуска. Каждый снимок обрабатывается дважды: текущей версией и экспериментальным исправлением левой границы. OCR и числовая проверка выполняются обычным пайплайном App.</p><p>Проверка арифметики не подтверждает автоматически наименование товара. Сырой OCR показан отдельно; название может требовать проверки в интерфейсе.</p><p>Это проверка двух конкретных фото, не оценка точности на произвольном корпусе. Рабочий сервер и его задания не изменяются.</p></section>
<section><h2>Найденные проблемы</h2><ul><li>Скотч: товар, числа, НДС и итог верны; в OCR шапки отсутствует строка номера заказа.</li><li>Насос: количество 1 остаётся пустым. Повторное чтение четырёх представлений даёт 1, но общий числовой повторный проход не подтверждает итог; защитная проверка не применяет изменения. Рабочий чек остаётся неполным, ложного подтверждения нет.</li></ul><p>Обе проблемы одинаково воспроизводятся в мастере и кандидате. На этих двух фото изображения Rectify совпали побайтово: расширение левой опоры не изменило результат. Эти проверки подтверждают отсутствие новых расхождений, но не доказывают устранение найденных ошибок и не являются полным PASS.</p></section>"""+''.join(cards)+f"<section><h2>Итог: {html.escape(summary['status'])}</h2><p>Исходные фото, .env и рабочая геометрия сохранены: {summary['protected_unchanged']}.</p><a href='../../data/eval/new_real_receipts_20261029/summary.json'>JSON-протокол</a></section></main></html>"
    report=ROOT/'docs/reports/new_real_receipts_2026-10-29.html'
    report.write_text(page,encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    protected=[ROOT/'.env',Path(contour_unwarp.__file__)]+[ROOT/'data/in_data'/case['file'] for case in CASES]
    hashes={str(path):sha(path) for path in protected}
    summary=dict(date='2026-10-29',status='running',cases=[])
    candidate=candidate_module()
    pipeline=ReceiptPipeline()
    for case in CASES:
        source=ROOT/'data/in_data'/case['file']
        record=dict(file=case['file'],input_sha256=sha(source),expected=case,runs=[])
        summary['cases'].append(record)
        for variant in ['master','candidate']:
            directory=OUT/case['number']/variant;directory.mkdir(parents=True,exist_ok=True)
            (directory/'upload.bin').write_bytes(source.read_bytes())
            job=Job(uuid.uuid4().hex,source.name,directory)
            print(f"Processing {case['number']} / {variant}",flush=True)
            run=dict(variant=variant,passed=False)
            try:
                builder=candidate.build_contour_map if variant=='candidate' else contour_unwarp.build_contour_map
                with patch.object(receipt_rectification,'build_contour_map',builder):
                    result=pipeline.process(job)
                products=[row for row in result['rows'] if row['kind']=='product']
                taxes=[row for row in result['rows'] if row['kind']=='tax']
                checks=dict(product_count=len(products)==1,tax_rows=len(taxes)==1,
                            quantity=len(products)==1 and parse_number(products[0]['quantity'])==Decimal(case['quantity']),
                            price=len(products)==1 and parse_number(products[0]['price'])==Decimal(case['price']),
                            vat=result['calculation']['tax_subtotal']==case['vat'],
                            computed_total=result['calculation']['computed_total']==case['total'],
                            printed_total=result['calculation']['expected_total']==case['total'],
                            validation=result['calculation']['validation_status']=='match',
                            order_number=result['order_number']==case['number'],date=result['date']=='26.10.2026')
                run.update(checks=checks,passed=all(checks.values()),products=products,calculation=result['calculation'],
                           order_number=result['order_number'],geometry=result['rectification_method'],
                           review_count=result['review_count'])
                print(json.dumps(dict(number=case['number'],variant=variant,passed=run['passed'],checks=checks,
                                      names=[row['name_raw'] for row in products]),ensure_ascii=False),flush=True)
            except Exception:
                run['error']=traceback.format_exc();print(run['error'],flush=True)
            record['runs'].append(run);write_summary(summary)
    summary['protected_unchanged']=all(sha(Path(path))==digest for path,digest in hashes.items())
    compare_runs(summary)
    summary['status']='passed' if summary['protected_unchanged'] and all(run['passed'] for case in summary['cases'] for run in case['runs']) else 'failed'
    write_summary(summary);render(summary)
    print('RESULT:',summary['status'],flush=True)
    if summary['status']!='passed':raise SystemExit(1)


if __name__=='__main__':
    main()
