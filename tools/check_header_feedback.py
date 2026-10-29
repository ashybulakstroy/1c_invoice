"""Check the reported receipt and visible explanations without changing its values."""
import copy
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from App.receipt_editing import update_receipt
from App.server_config import server_settings
BASE_URL = server_settings().browser_url

OUT = ROOT / 'data/eval/header_fix_20261027'
SOURCE = ROOT / 'web_outputs/80f29dad978b438fb1ef135879c5cff3'


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
        page = browser.new_page(viewport=dict(width=1440, height=1000))
        page.route('**/favicon.ico', lambda route: route.fulfill(status=204))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(BASE_URL + '/?new=1', wait_until='networkidle')
        page.locator('#file-input').set_input_files(dict(name='reported_receipt.png', mimeType='image/png', buffer=(SOURCE/'upload.bin').read_bytes()))
        page.wait_for_function('state.result !== null', timeout=120000)
        result = page.evaluate('state.result')
        assert result['product_count'] == 11
        assert len(result['rows']) == 12
        assert result['calculation']['validation_status'] == 'match'
        assert result['calculation']['vat']['status'] == 'match'
        assert result['calculation']['computed_total'] == '230214.00'
        assert not any(row['quantity_raw'] == 'Саны' for row in result['rows'])
        assert page.locator('#receipt-errors').is_hidden()
        assert page.locator('.invalid-number,.vat-failed,.math-failed').count() == 0
        page.wait_for_function("document.querySelector('.math-success-flash') === null")
        page.locator('#receipt-body tr').first.scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'corrected_receipt.png'))

        # UI-only cases: never POST artificial corrections to real receipt data.
        def show(value):
            page.evaluate('result => finish(result)', value)
            return page.locator('#receipt-error-reasons').inner_text()

        incomplete = json.loads((OUT/'receipt.json').read_text(encoding='utf-8'))
        text = show(incomplete)
        assert 'Саны' in text and 'Багасы' in text
        assert 'не завершена' in text and 'не подтверждённая ошибка' in text
        assert page.locator('.math-success-flash').count() == 0
        page.locator('#receipt-errors').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'validation_explanation_example.png'))

        mismatch = copy.deepcopy(result)
        mismatch['expected_total'] = '230215'
        mismatch['expected_total_source'] = 'user'
        text = show(update_receipt(mismatch))
        assert '230 214,00' in text and '230 215,00' in text and '-1,00' in text

        wrong_tax = copy.deepcopy(result)
        next(row for row in wrong_tax['rows'] if row['kind'] == 'tax')['quantity'] = '31753'
        wrong_tax['expected_total'] = '230213'
        wrong_tax['expected_total_source'] = 'user'
        text = show(update_receipt(wrong_tax))
        assert 'НДС не совпадает' in text and '31 753,00' in text and '31 754,00' in text and '16%' in text
        assert page.locator('.vat-failed').count() == 1

        missing = copy.deepcopy(result)
        missing['expected_total'] = ''
        missing['expected_total_source'] = 'user'
        assert 'итог с фотографии не прочитан' in show(update_receipt(missing))
        show(result)
        assert page.locator('#receipt-errors').is_hidden()
        page.set_viewport_size(dict(width=390, height=844))
        show(incomplete)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        report = dict(job_id=result['job_id'], products=11, total='230214.00', vat='31754.00',
                      real_ocr=True, header_excluded=True, numeric_explanation=True,
                      total_mismatch_explanation=True, vat_explanation=True,
                      missing_total_explanation=True, messages_clear_after_correction=True,
                      mobile=True, errors=errors)
        (OUT/'browser_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        browser.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
