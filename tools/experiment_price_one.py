"""CPU-only, isolated A/B gate for missing one-tenge prices on latest ten receipts."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import copy, hashlib, html, importlib.util, json, sys, time, uuid, types, subprocess
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
cv2.setNumThreads(1)
import rapidocr_onnxruntime.utils as ortutils
original_options=ortutils.SessionOptions
def options():
    result=original_options();result.intra_op_num_threads=1;result.inter_op_num_threads=1
    return result
ortutils.SessionOptions=options
from App import numeric_recovery, web_pipeline
from App.web_server import Job
from App.receipt_editing import parse_number
from decimal import Decimal
baseline_source=subprocess.check_output(['git','show','e83764e:App/numeric_recovery.py'],cwd=ROOT).decode('utf-8')
baseline=types.ModuleType('price_experiment_master')
exec(compile(baseline_source,'master_numeric_recovery.py','exec'),baseline.__dict__)
spec=importlib.util.spec_from_file_location('price_candidate',ROOT/'experiments/selective_price_ocr_candidate.py')
candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)
OUT=ROOT/'data/eval/price_one_20261030'

def candidate_recover(receipt,image,layout,lines,recognize,**kwargs):
    recovered,audit=candidate.recover_missing_prices(receipt,image,layout,recognize,ocr_lock=kwargs.get('ocr_lock'))
    result,report=baseline.recover_numeric_receipt(recovered,image,layout,lines,recognize,**kwargs)
    report['selective_price']=audit
    report['applied']=audit['applied']+report['applied'];report['applied_count']=len(report['applied'])
    return result,report

def cases():
    found=[];seen=set();numbers=set()
    for photo in sorted((ROOT/'web_outputs').glob('*/upload.bin'),key=lambda p:p.stat().st_mtime,reverse=True):
        path=photo.parent/'receipt.json'
        if not path.exists():continue
        receipt=json.loads(path.read_text(encoding='utf-8'))
        digest=hashlib.sha256(photo.read_bytes()).hexdigest()
        number=receipt.get('order_number')
        if digest in seen or number and number in numbers:continue
        seen.add(digest);numbers.add(number)
        found.append(dict(photo=str(photo.relative_to(ROOT)),sha256=digest,number=number))
        if len(found)==10:break
    return found

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    pipeline=web_pipeline.ReceiptPipeline()
    started=time.perf_counter();pipeline.resources();cold=time.perf_counter()-started
    pipeline.engine.text_recognizer([255*__import__('numpy').ones((48,160,3),dtype='uint8')])
    summary=dict(cold_model_and_catalog_seconds=cold,threads=1,CPU=True,hot_repetitions=1,
                 baseline_commit='e83764e',baseline_sha256=hashlib.sha256(baseline_source.encode()).hexdigest(),cases=[])
    for index,case in enumerate(cases()):
        result=dict(**case,runs={});summary['cases'].append(result)
        for variant in (['master','candidate'] if index%2==0 else ['candidate','master']):
            directory=OUT/f'{index:02d}_{case["number"]}'/variant;directory.mkdir(parents=True,exist_ok=True)
            (directory/'upload.bin').write_bytes((ROOT/case['photo']).read_bytes())
            job=Job(uuid.uuid4().hex,Path(case['photo']).name,directory)
            started=time.perf_counter()
            with patch.object(web_pipeline,'recover_numeric_receipt',candidate_recover if variant=='candidate' else baseline.recover_numeric_receipt):
                receipt=pipeline.process(job)
            seconds=time.perf_counter()-started
            job.json_file('receipt.json',receipt)
            audit=json.loads((directory/'numeric_recovery.json').read_text(encoding='utf-8'))
            result['runs'][variant]=dict(seconds=seconds,receipt=receipt,audit=audit,path=str(directory.relative_to(ROOT)),
                stages=[e for e in job.events if e.get('type')=='stage' and e.get('status')=='done'])
            print(case['number'],variant,round(seconds,2),receipt['calculation']['status'],flush=True)
        before=result['runs']['master']['receipt'];after=result['runs']['candidate']['receipt']
        regressions=[];changes=[]
        old={r['row']:r for r in before['rows']};new={r['row']:r for r in after['rows']}
        if old.keys()!=new.keys():regressions.append('row_ids')
        for row_id,row in old.items():
            other=new.get(row_id,{})
            for field in ('name_raw','name','kind','quantity_raw','price_raw','quantity','price'):
                if row.get(field)==other.get(field):continue
                if field=='price' and parse_number(row.get(field)) is None and parse_number(other.get(field)) is not None:
                    changes.append(dict(row=row_id,field=field,before=row.get(field),after=other.get(field)))
                else:regressions.append(dict(row=row_id,field=field,before=row.get(field),after=other.get(field)))
        for field in ('expected_total','order_number','date'):
            if before.get(field)!=after.get(field):regressions.append(field)
        for field in ('status','validation_status'):
            if before['calculation'].get(field)=='match' and after['calculation'].get(field)!='match':regressions.append('calculation.'+field)
        result.update(regressions=regressions,changes=changes)
        (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    summary['no_regressions']=all(not c['regressions'] for c in summary['cases'])
    summary['sources_unchanged']=all(hashlib.sha256((ROOT/c['photo']).read_bytes()).hexdigest()==c['sha256'] for c in summary['cases'])
    target=next(c for c in summary['cases'] if c['number']=='945006016')
    receipt=target['runs']['candidate']['receipt']
    summary['target_correct']=all(parse_number(r.get('price'))==Decimal(1) for r in receipt['rows'] if r['kind'] in {'service','product','tax'}) and receipt['calculation']['computed_total']=='17400.00' and receipt['calculation']['validation_status']=='match'
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('GATE',summary['no_regressions'],summary['target_correct'],summary['sources_unchanged'],flush=True)

if __name__=='__main__':main()
