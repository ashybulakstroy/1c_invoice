"""Isolated browser acceptance of the actual invoice UI and HTTP handlers."""
from __future__ import annotations
import copy
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright, expect
from App.web_server import create_server
from App.invoicing import invoice_service
from App.tests.test_invoicing_invoice_api import RECEIPT

OUT = ROOT / "data/eval/invoice_browser_20261029"
EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original_train = invoice_service.train_from_selections
    def isolated_train(receipt, selections):
        return original_train(receipt, selections, knowledge_path=OUT / "knowledge.json",
                              training_dir=OUT / "training")
    invoice_service.train_from_selections = isolated_train
    def process(job):
        receipt = copy.deepcopy(RECEIPT)
        receipt.update(job_id=job.id, product_count=3, review_count=0, pass_similarity=87)
        job.json_file("receipt.json", receipt)
        return receipt
    server = create_server("127.0.0.1", 0, OUT / "jobs", process)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks, errors = {}, []
    try:
        job = server.store.submit(b"synthetic browser test", "synthetic.png")
        deadline = time.monotonic() + 15
        while job.status not in {"done", "failed"} and time.monotonic() < deadline:
            time.sleep(.05)
        assert job.status == "done", job.error
        receipt_path = job.directory / "receipt.json"
        original_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        base = f"http://127.0.0.1:{server.server_port}"
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EDGE, headless=True)
            page = browser.new_page(viewport={"width":1600,"height":1100}, accept_downloads=True)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(f"localStorage.setItem('receipt-last-job', '{job.id}')")
            page.goto(base, wait_until="networkidle")
            expect(page.locator("#invoice-content")).to_be_visible(timeout=20000)
            expect(page.locator(".inv-row")).to_have_count(3)
            checks["invoice_panel"] = True
            checks["no_unrequested_fields"] = page.locator("#invoice-buyer,#invoice-contract").count() == 0
            expect(page.locator("#invoice-print-preview")).to_be_visible(timeout=20000)
            expect(page.locator("#invoice-pdf")).to_be_visible()
            checks["automatic_unmapped_preview"] = True
            for index in range(3):
                row = page.locator(".inv-row").nth(index)
                row.locator(".inv-search").fill("00000019603")
                expect(row.locator(".inv-option").first).to_be_visible()
                row.locator(".inv-option").first.click()
            checks["catalog_selection"] = page.locator(".inv-selection").count() == 3
            # A user change must hide any PDF based on old selections.
            page.locator(".inv-qty").first.fill("2")
            page.locator(".inv-qty").first.press("Tab")
            expect(page.locator("#invoice-pdf")).to_be_hidden()
            page.locator("#invoice-preview").click()
            expect(page.locator("#invoice-print-preview")).to_be_visible(timeout=20000)
            assert not (job.directory / "invoice_state.json").exists()
            checks["unsaved_pdf_preview"] = True
            with page.expect_download() as download_event:
                page.locator("#invoice-pdf").click()
            download_event.value.save_as(OUT / "preview.pdf")
            checks["download"] = (OUT / "preview.pdf").read_bytes().startswith(b"%PDF")
            page.locator("#invoice-save").click()
            expect(page.locator("#invoice-save")).to_be_enabled(timeout=20000)
            assert (job.directory / "invoice_state.json").exists()
            checks["save"] = True
            page.reload(wait_until="networkidle")
            expect(page.locator(".inv-selection")).to_have_count(3, timeout=20000)
            expect(page.locator("#invoice-save")).to_be_enabled(timeout=20000)
            expect(page.locator(".inv-qty").first).to_have_value("2")
            checks["reload_preserves_choice"] = True
            # Replace an existing choice through a different real catalog card.
            row = page.locator(".inv-row").first
            with page.expect_response(lambda response: '/api/catalog-1c?q=' in response.url):
                row.locator(".inv-search").fill("цемент")
            page.wait_for_function("document.querySelector('.inv-row .inv-option')?.textContent.toLowerCase().includes('цемент')")
            expect(row.locator(".inv-option").first).to_be_visible()
            row.locator(".inv-option").first.click()
            expect(page.locator("#invoice-pdf")).to_be_hidden()
            page.locator("#invoice-save").click()
            expect(page.locator("#invoice-save")).to_be_enabled(timeout=20000)
            checks["replace_choice"] = True
            page.locator("#invoice-train").click()
            expect(page.locator("#toast")).to_contain_text("Обучение сохранено", timeout=20000)
            checks["explicit_training"] = bool(list((OUT / "training").glob("case_*/expected.json")))
            page.locator("#invoice-panel").scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
            page.set_viewport_size({"width":390,"height":844})
            checks["mobile_no_page_overflow"] = page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
            checks["receipt_unchanged"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest() == original_hash
            checks["no_page_errors"] = not errors
            browser.close()
        import pypdfium2
        pdf = pypdfium2.PdfDocument(str(OUT / "preview.pdf"))
        pdf[0].render(scale=1.4).to_pil().save(OUT / "preview.png")
    finally:
        invoice_service.train_from_selections = original_train
        server.shutdown(); server.server_close(); server.store.pool.shutdown(wait=True)
        thread.join(timeout=3)
        (OUT / "results.json").write_text(json.dumps({"checks":checks,"errors":errors},ensure_ascii=False,indent=2),encoding="utf-8")
    assert all(checks.values()), checks
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
