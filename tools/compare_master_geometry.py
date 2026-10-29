"""Isolated A/B check; experimental side-fit change is NOT installed in App."""
import argparse
import hashlib
import html
import importlib.util
import json
import sys
import types
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from App import contour_unwarp
from App.ocr_catalog_eval import aligned_lines, choose_row_boundaries, parse_rows, table_layout
from App.ocr_run import MODEL
from App.receipt_editing import parse_number, update_receipt
from App.receipt_rectification import rectify_table
from App.wave_dewarp import find_rules
from rapidocr_onnxruntime import RapidOCR


def load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate_module():
    # Explicit research variation: admit the missing top-left contour vertex
    # only if the original narrow side band has no supported vertical span.
    # The production master is kept byte-for-byte unchanged by this experiment.
    source = Path(contour_unwarp.__file__).read_text(encoding='utf-8')
    needle = 'select = (x < .1 if left else x > .9)'
    assert source.count(needle) == 1
    module = types.ModuleType('isolated_wider_side_support')
    module.__file__ = str(Path(contour_unwarp.__file__).resolve())
    replacement = (needle + '\n'
                   '        if left and (len(np.unique(y[select])) < 2 or np.ptp(y[select]) < .5):\n'
                   '            select = x < .2')
    exec(compile(source.replace(needle, replacement),
                 '<isolated contour side-fit candidate>', 'exec'), module.__dict__)
    return module


def metrics(image):
    rules, _ = find_rules(image, vertical=True)
    return dict(vertical_rule_count=len(rules),
                vertical_drift_px=[round(float(np.ptp(rule.values)), 2) for rule in rules])


def validate_candidate():
    tests = load_file(ROOT/'App/tests/test_contour_unwarp.py', 'isolated_contour_regression_tests')
    tests.build_contour_map = candidate_module().build_contour_map
    results = []
    for name, function in vars(tests).items():
        if not name.startswith('test_'):
            continue
        try:
            function()
            results.append(dict(test=name, passed=True))
        except Exception as error:
            results.append(dict(test=name, passed=False, error=f'{type(error).__name__}: {error}'))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', default='80f29dad978b438fb1ef135879c5cff3')
    parser.add_argument('--out', type=Path, default=ROOT/'data/eval/master_import_20261029/geometry')
    args = parser.parse_args()
    job = ROOT/'web_outputs'/args.job
    args.out.mkdir(parents=True, exist_ok=True)
    image = cv2.imdecode(np.frombuffer((job/'upload.bin').read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    original_meta = json.loads((job/'rectification.json').read_text(encoding='utf-8'))
    polygon = np.asarray(original_meta['source_polygon'], np.float32)
    old = load_file(ROOT/'.backups/master_import_20261029/App/contour_unwarp.py', 'previous_contour')
    candidate = candidate_module()
    before_hash = hashlib.sha256(Path(contour_unwarp.__file__).read_bytes()).hexdigest()
    variants = []
    for name, module in [('previous', old), ('master', contour_unwarp), ('candidate', candidate)]:
        mx, my, meta = module.build_contour_map(polygon)
        output = cv2.remap(image, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255,255,255))
        variants.append((name, output, meta))
    selected, _, _, selected_meta = rectify_table(image, polygon)
    variants.append(('master_selector', selected, selected_meta))
    engine = RapidOCR(rec_model_path=str(MODEL), rec_img_shape=[3,48,320], text_score=.3)
    reports = []
    for name, output, meta in variants:
        directory = args.out/name; directory.mkdir(exist_ok=True)
        cv2.imencode('.png', output)[1].tofile(str(directory/'rectified.png'))
        raw, _ = engine(output)
        payload = dict(lines=[dict(text=str(text), confidence=float(confidence), box=np.asarray(box).tolist(),
                                   box_original=np.asarray(box).tolist()) for box,text,confidence in raw or []])
        (directory/'ocr.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        layout = table_layout(output, meta)
        lines = aligned_lines(payload, meta)
        boundaries, segmentation = choose_row_boundaries(lines, layout)
        rows = parse_rows(lines, layout, boundaries)
        totals = [line for line in lines if line['center'][1] >= layout['body_bottom'] - 5
                  and line['center'][0] > layout['name_right'] and parse_number(line['text']) is not None]
        printed_total = max(totals, key=lambda line: line['center'][1])['text'] if totals else ''
        receipt = update_receipt(dict(rows=rows, total_raw=printed_total, pass_similarity=87))
        products = [row for row in rows if row['kind']=='product']
        third = next((row for row in products if row.get('item_number_raw')=='3'), products[2] if len(products)>2 else {})
        result = dict(variant=name, source_body_corners=meta.get('source_body_corners'),
                      fitted_left=meta.get('fitted_left'), method=meta['method'],
                      metrics=metrics(output), product_count=len(products),
                      third_product={key:third.get(key) for key in ('item_number_raw','name_raw','quantity_raw','price_raw')},
                      calculation=receipt['calculation'], rows=rows, segmentation=segmentation)
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        reports.append(result)
        print(json.dumps({key:result[key] for key in ('variant','metrics','product_count','third_product','calculation')},ensure_ascii=False),flush=True)
    assert hashlib.sha256(Path(contour_unwarp.__file__).read_bytes()).hexdigest()==before_hash
    summary = dict(source_job=args.job, production_geometry_unchanged=True, results=reports,
                   isolated_candidate_tests=validate_candidate())
    (args.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    cards = ''.join(f'<section><h2>{html.escape(row["variant"])}</h2><p>{html.escape(json.dumps(row["third_product"],ensure_ascii=False))}</p>'
                    f'<p>Дрейф вертикалей: {html.escape(str(row["metrics"]["vertical_drift_px"]))} px</p>'
                    f'<img src="{row["variant"]}/rectified.png"></section>' for row in reports)
    (args.out/'index.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Геометрия: отдельный A/B тест</title>'
        '<style>body{font:15px Segoe UI;margin:30px;color:#19304d}main{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}img{width:100%}section{min-width:0}p{overflow-wrap:anywhere}</style>'
        '<h1>Отдельная проверка геометрии · 29.10.2026</h1><p>Candidate — исследовательский вариант, не подключённый к рабочему конвейеру.</p><main>'+cards+'</main></html>',encoding='utf-8')


if __name__=='__main__':
    main()
