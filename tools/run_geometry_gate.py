"""Synthetic gate, then two real receipts in an isolated production pipeline."""
import copy
import hashlib
import html
import json
import re
import sys
import traceback
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare_master_geometry import candidate_module, validate_candidate
from App import contour_unwarp, receipt_rectification
from App.receipt_editing import parse_number
from App.web_pipeline import ReceiptPipeline
from App.web_server import Job

OUT = ROOT / 'data/eval/geometry_gate_20261029'


def save(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def synthetic_gate(candidate):
    controls = validate_candidate()
    trials = []
    random = np.random.default_rng(20261029)
    for index in range(100):
        width = float(random.integers(200, 440))
        height = float(random.integers(320, 690))
        slant = float(random.uniform(-.15, .18) * width)
        top_drop = float(random.uniform(-.025, .05) * height)
        footer = float(random.integers(12, 35))
        x0, y0 = 110., 90.
        polygon = np.array([[x0+slant,y0], [x0,y0+height],
                            [x0+width*.6,y0+height], [x0+width*.6,y0+height+footer],
                            [x0+width,y0+height+footer], [x0+width,y0+top_drop]])
        trial = dict(case=index, slant_px=slant, top_drop_px=top_drop)
        try:
            mx, my, meta = candidate.build_contour_map(polygon)
            margin = meta['margin']
            w, h = meta['body_size']
            # The independently generated source polygon supplies the reference.
            expected = np.array([[x0+slant,y0], [x0+width,y0+top_drop],
                                 [x0+width,y0+height], [x0,y0+height]])
            actual = np.array([[mx[y,x],my[y,x]] for x,y in
                               [(margin,margin),(margin+w-1,margin),
                                (margin+w-1,margin+h-1),(margin,margin+h-1)]])
            error = float(np.max(np.linalg.norm(actual-expected,axis=1)))
            trial.update(max_corner_error_px=error, min_jacobian=meta['min_jacobian'])
            assert np.isfinite(mx).all() and np.isfinite(my).all(), 'Non-finite sampling map'
            assert meta['min_jacobian'] > .02, 'Folded or collapsed map'
            assert error < .2, f'Wrong source corner: {error:.3f} px'
            assert meta['footer_height'] >= 8, 'Total strip was lost'
            # Cases supported by the old side band must remain pixel-identical.
            before_x,before_y,_ = contour_unwarp.build_contour_map(polygon)
            normalized=(polygon-polygon.min(axis=0))/np.ptp(polygon,axis=0)
            ys=normalized[normalized[:,0]<.1,1]
            supported=len(np.unique(ys))>=2 and np.ptp(ys)>=.5
            if supported:
                assert np.array_equal(mx,before_x) and np.array_equal(my,before_y), 'Unnecessary geometry change'
            trial.update(passed=True,original_side_supported=bool(supported))
        except Exception as error:
            trial.update(passed=False,error=f'{type(error).__name__}: {error}')
        trials.append(trial)
    return dict(seed=20261029, controls=controls, trials=trials,
                passed=all(row['passed'] for row in controls+trials))


def real_checks(candidate):
    cases = [
        dict(name='receipt_2142736988', source=ROOT/'web_outputs/80f29dad978b438fb1ef135879c5cff3/upload.bin',
             products=11, total='230214.00', vat='31754.00',
             numeric=[('2','36530'),('100','200'),('20','300'),('10','640'),('10','400'),
                      ('10','380'),('5','260'),('2','2400'),('200','280'),('2','7800'),('2','3750')]),
        dict(name='receipt_596753', source=ROOT/'App/tests/fixtures/wavy_receipt_596753.png',
             products=2, total='247780.00', vat='0.00', numeric=[('1','5780'),('1','242000')]),
    ]
    pipeline = ReceiptPipeline()
    reports = []
    for case in cases:
        digest = hashlib.sha256(case['source'].read_bytes()).hexdigest()
        report = dict(receipt=case['name'], source=str(case['source']), input_sha256=digest, runs=[])
        for variant in ['master','candidate']:
            directory = OUT/case['name']/variant
            directory.mkdir(parents=True,exist_ok=True)
            (directory/'upload.bin').write_bytes(case['source'].read_bytes())
            job = Job(uuid.uuid4().hex, case['source'].name, directory)
            builder = candidate.build_contour_map if variant=='candidate' else contour_unwarp.build_contour_map
            print(f"Starting real receipt {case['name']} / {variant}",flush=True)
            # Patch only this isolated process; the live web server is unaffected.
            with patch.object(receipt_rectification,'build_contour_map',builder):
                result = pipeline.process(job)
            products = [row for row in result['rows'] if row['kind']=='product']
            numbers = [(parse_number(row['quantity']),parse_number(row['price'])) for row in products]
            expected = [(Decimal(q),Decimal(p)) for q,p in case['numeric']]
            checks = dict(product_count=len(products)==case['products'], numeric_values=numbers==expected,
                          total=result['calculation']['computed_total']==case['total'],
                          original_total=result['calculation']['expected_total']==case['total'],
                          vat=result['calculation']['tax_subtotal']==case['vat'],
                          validation=result['calculation']['validation_status']=='match')
            if case['products']==11 and variant=='candidate':
                checks['third_number_separated']=products[2]['item_number_raw']=='3'
                checks['third_name_without_row_number']=not bool(re.search(r'\b3\b',products[2]['name_raw']))
            record=dict(variant=variant,checks=checks,passed=all(checks.values()),
                        geometry=result['rectification_method'],calculation=result['calculation'],
                        products=[{key:row.get(key) for key in ('row','item_number_raw','name_raw','quantity','price')}
                                  for row in products])
            report['runs'].append(record)
            print(json.dumps(dict(receipt=case['name'],variant=variant,passed=record['passed'],checks=checks),ensure_ascii=False),flush=True)
        assert hashlib.sha256(case['source'].read_bytes()).hexdigest()==digest, 'Source image changed'
        report['passed']=all(run['passed'] for run in report['runs'])
        reports.append(report)
    return reports


def render(summary):
    gate=summary['synthetic']
    control_count=sum(row['passed'] for row in gate['controls'])
    trial_count=sum(row['passed'] for row in gate['trials'])
    cards=[]
    for case in summary.get('real_receipts',[]):
        runs=[]
        for run in case['runs']:
            third=run['products'][2] if len(run['products'])>2 else run['products'][0]
            runs.append(f"<h3>{html.escape(run['variant'])} · {'PASS' if run['passed'] else 'FAIL'}</h3>"
                        f"<p>Товаров: {len(run['products'])}; итог: {html.escape(run['calculation']['computed_total'])}; "
                        f"НДС: {html.escape(run['calculation']['tax_subtotal'])}</p>"
                        f"<p>{html.escape(json.dumps(third,ensure_ascii=False))}</p>"
                        f"<img src='../../data/eval/geometry_gate_20261029/{case['receipt']}/{run['variant']}/rectified.png'>")
        cards.append(f"<section><h2>{html.escape(case['receipt'])}</h2><div class='compare'>"+
                     ''.join('<div>'+item+'</div>' for item in runs)+'</div></section>')
    failures=[row for row in gate['controls']+gate['trials'] if not row['passed']]
    page=f"""<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Проверка геометрии · 29.10.2026</title><style>body{{font:16px/1.65 Segoe UI;background:#f2f5fa;color:#18304e;margin:0}}main{{max-width:1120px;margin:auto;padding:25px}}section,header{{padding:24px;background:white;border:1px solid #dce4f0;border-radius:16px;margin-bottom:20px}}header{{background:#172e53;color:white}}.compare{{display:grid;grid-template-columns:1fr 1fr;gap:25px}}img{{width:100%}}p{{overflow-wrap:anywhere}}@media(max-width:650px){{.compare{{grid-template-columns:1fr}}}}</style><main>
<header><h1>Проверка экспериментальной геометрии</h1><p>29.10.2026 · Сначала синтетический этап, затем два настоящих фото</p></header>
<section><h2>Синтетический этап: {'PASS' if gate['passed'] else 'FAIL'}</h2><p>Контрольные проверки: {control_count}/{len(gate['controls'])}.
Сгенерированные варианты: {trial_count}/{len(gate['trials'])}. Seed: {gate['seed']}.</p>
<p>Проверены известные углы исходного контура (допуск 0,2 px), конечность карты, отсутствие складок, сохранение полосы итога и неизменность карты там, где исходная опора достаточна.</p>
<p>Это синтетическая проверка геометрии, не статистическая оценка точности OCR на реальной выборке.</p>
<pre>{html.escape(json.dumps(failures,ensure_ascii=False,indent=2)) if failures else 'Ошибок нет'}</pre></section>
<section><h2>Реальные фото</h2><p>Полный пайплайн текущего App запускается в отдельном процессе, с настоящим RapidOCR и текущим каталогом.
Для каждого фото проверяются мастер и кандидат. Сверяются все количества/цены, число товаров, исходный и вычисленный итог, НДС; для чека с валиком — отделение номера 3.</p>
<p>Проверенные числа служат независимым эталоном теста; они не подставляются в OCR или результат пайплайна.</p>
<p>Кандидат не подключается к рабочему серверу; исходные фото, .env и производственный код не изменяются.</p></section>
{''.join(cards)}<section><h2>Итог: {html.escape(summary['status'])}</h2><p>Подробности: <a href='../../data/eval/geometry_gate_20261029/summary.json'>JSON-протокол</a>.</p></section></main></html>"""
    path=ROOT/'docs/reports/geometry_gate_2026-10-29.html'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(page,encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    protected=[Path(contour_unwarp.__file__),ROOT/'.env']
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    candidate=candidate_module()
    summary=dict(status='running',synthetic=synthetic_gate(candidate),real_receipts=[])
    save('synthetic.json',summary['synthetic'])
    print('Synthetic:',sum(row['passed'] for row in summary['synthetic']['controls']+summary['synthetic']['trials']),
          '/',len(summary['synthetic']['controls']+summary['synthetic']['trials']),flush=True)
    if not summary['synthetic']['passed']:
        summary['status']='synthetic_failed_real_stage_not_started'
    else:
        try:
            summary['real_receipts']=real_checks(candidate)
            summary['status']='passed' if all(case['passed'] for case in summary['real_receipts']) else 'real_receipt_failed'
        except Exception:
            summary['status']='real_stage_error';summary['error']=traceback.format_exc()
    summary['production_code_and_env_unchanged']=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in before.items())
    save('summary.json',summary);render(summary)
    print(summary['status'],flush=True)
    if summary['status']!='passed':raise SystemExit(1)


if __name__=='__main__':
    main()
