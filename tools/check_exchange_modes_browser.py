"""Real HTTP/browser acceptance, isolated data; --real runs an actual receipt OCR."""
import argparse
import copy
import json
from pathlib import Path
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright, expect
from App.web_server import create_server
from App.tests.test_invoicing_invoice_api import RECEIPT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real', action='store_true')
    args = parser.parse_args()
    out = ROOT / 'data/eval/dual_mode_20261101' / ('real' if args.real else 'synthetic') / uuid.uuid4().hex[:8]
    out.mkdir(parents=True)
    def process(job):
        result = copy.deepcopy(RECEIPT)
        result.update(job_id=job.id, product_count=3, review_count=0)
        job.json_file('receipt.json', result)
        return result
    server = create_server('127.0.0.1', 0, out/'jobs', None if args.real else process)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    checks = {}
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror',lambda error: errors.append(str(error)))
            body={'database_id':'local','request_id':str(uuid.uuid4())}
            created=page.request.post(base+'/tasks',data=body).json()
            task_id=created['task_id']
            task_url=base+f'/tasks/{task_id}'
            result_url=task_url+'/result'
            assert page.request.get(result_url).status==202
            assert page.request.get(result_url+'?allow_unconfirmed=1').status==202
            page.goto(task_url+'/ui')
            page.wait_for_function("document.getElementById('connection-text').textContent==='Сервер доступен'")
            expect(page.locator('#invoice-confirm')).to_be_disabled()
            photo=(ROOT/'data/in_data/WhatsApp Image 2026-10-26 at 09.02.00.jpeg' if args.real
                   else ROOT/'App/tests/fixtures/wavy_receipt_596753.png')
            page.locator('#file-input').set_input_files(photo)
            page.wait_for_function('state.result!==null',timeout=180000)
            expect(page.locator('#invoice-content')).to_be_visible(timeout=20000)
            expect(page.locator('#invoice-confirm')).to_be_enabled(timeout=20000)
            checks['automatic_pdf']=page.locator('#invoice-print-preview').is_visible()
            assert page.request.get(result_url).status==202
            response=page.request.get(result_url+'?allow_unconfirmed=1')
            assert response.status==200,response.text()
            draft=response.json()
            assert draft['status']=='ready_unconfirmed' and draft['ocr_complete']
            assert page.request.get(result_url+'?allow_unconfirmed=1').json()==draft
            assert page.request.get(task_url+'/ui/state').json()['state']=='review'
            expect(page.locator('#ocr-confirm-success')).to_be_hidden()
            checks['draft_without_confirmation']=True
            # A rejected server response must not show success or lose edits.
            for failure in (202,409,500,'network'):
                def fail(route):
                    if failure=='network':route.abort()
                    else:route.fulfill(status=failure,content_type='application/json',body='{"error":"Проверка отказа"}')
                page.route('**/confirm',fail)
                page.locator('#invoice-confirm').click()
                expect(page.locator('#invoice-confirm-error')).to_be_visible()
                expect(page.locator('#ocr-confirm-success')).to_be_hidden()
                page.unroute('**/confirm')
            checks['failure_no_success']=True
            # An actual manual candidate choice is saved by the confirm handler.
            page.locator('#invoice-edit-products').click()
            option=page.locator('.inv-row').first.locator('.inv-option').first
            expect(option).to_be_visible()
            chosen=option.locator('.inv-option-name').inner_text()
            option.click()
            with page.expect_response(lambda response:'/confirm' in response.url) as confirm:
                page.locator('#invoice-confirm').click()
            assert confirm.value.status==200,confirm.value.text()
            expect(page.locator('#ocr-confirm-success')).to_be_visible()
            page.wait_for_function("document.activeElement.id==='ocr-confirm-success'")
            page.wait_for_function("(()=>{const r=document.getElementById('ocr-confirm-success').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight})()")
            snapshot=page.request.get(result_url).json()
            assert snapshot['status']=='confirmed'
            assert ' '.join(snapshot['items'][0]['target']['name'].split())==' '.join(chosen.split())
            assert all(not item['target']['price_includes_vat'] for item in snapshot['items'])
            assert page.request.post(task_url+'/confirm',data={'revision':snapshot['revision']}).json()['result_version']==snapshot['result_version']
            checks['saved_choice_and_idempotent_confirmation']=True
            checks['success_focus']=True
            page.screenshot(path=str(out/'confirmed.png'))
            page.reload()
            expect(page.locator('#ocr-confirm-success')).to_be_visible(timeout=20000)
            checks['reload_restores_success']=True
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#ocr-confirm-success').scroll_into_view_if_needed()
            page.screenshot(path=str(out/'mobile.png'))
            checks['mobile_no_overflow']=page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
            assert checks['mobile_no_overflow']
            assert not errors,errors
            current_receipt=page.evaluate('state.result')
            edited=page.request.post(base+f"/api/jobs/{current_receipt['job_id']}/edits",data={
                'revision':current_receipt['revision'],'expected_total':current_receipt['expected_total']})
            assert edited.status==200,edited.text()
            assert page.request.get(result_url).status==202
            page.reload()
            expect(page.locator('#invoice-confirm')).to_be_enabled(timeout=20000)
            expect(page.locator('#ocr-confirm-success')).to_be_hidden()
            checks['edit_hides_success_and_requires_new_confirmation']=True
            checks['no_page_errors']=True
            (out/'snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
    finally:
        server.shutdown();server.server_close();server.store.pool.shutdown(wait=True)
        thread.join(timeout=3)
    (out/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'out':str(out),'checks':checks},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
