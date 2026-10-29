"""Smoke check of the running App using the included receipt fixture."""
import hashlib
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from App.server_config import server_settings
BASE_URL = server_settings().browser_url
OUT = ROOT / "data/eval/startup_20261027"
EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=EDGE, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/favicon.ico", lambda route: route.fulfill(status=204))
        errors = []
        console_errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(BASE_URL + "/?new=1", wait_until="networkidle")
        assert page.locator("#connection-text").inner_text() == "Сервер доступен"
        page.screenshot(path=str(OUT / "browser_empty.png"))
        page.locator("#file-input").set_input_files(ROOT / "App/tests/fixtures/wavy_receipt_596753.png")
        page.wait_for_function("state.result !== null", timeout=120000)
        result = page.evaluate("state.result")
        assert result["product_count"] == 2
        assert result["calculation"]["validation_status"] == "match"
        assert result["calculation"]["computed_total"] == "247780.00"
        assert page.locator(".image-card").count() >= 3
        assert page.locator(".image-card[data-key=rectified] .cell-box").count() == len(result["rows"]) * 4
        events_response = page.request.get(f"{BASE_URL}/api/jobs/{result['job_id']}/events")
        events = [json.loads(line[6:]) for line in events_response.text().splitlines() if line.startswith("data: ")]
        assert any(event["type"] == "draft_rows" for event in events)
        raw = ROOT / "web_outputs" / result["job_id"] / "ocr_rectified.json"
        before = hashlib.sha256(raw.read_bytes()).hexdigest()
        page.screenshot(path=str(OUT / "browser_receipt.png"))
        # Save the same printed total to exercise a real edit without approving names.
        page.locator("#editor-panel").evaluate("element => {element.open = true}")
        page.locator("#edit-expected-total").fill(result["calculation"]["expected_total"])
        page.locator("#save-total").click()
        page.wait_for_function("revision => state.result.revision > revision && !state.saving", arg=result["revision"])
        assert before == hashlib.sha256(raw.read_bytes()).hexdigest()
        with page.expect_download() as download:
            page.locator("#download-json").click()
        download.value.save_as(OUT / "browser_download_receipt.json")
        page.reload(wait_until="networkidle")
        page.wait_for_function("state.result !== null")
        assert page.evaluate("state.result.job_id") == result["job_id"]
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / "browser_mobile.png"))
        assert not errors, errors
        assert not console_errors, console_errors
        report = dict(job_id=result["job_id"], upload=True, real_ocr=True, live_events=True,
                      grid=True, total="247780.00", total_edit=True, raw_ocr_preserved=True,
                      json_download=True, restore=True, mobile=True, page_errors=errors, console_errors=console_errors)
        (OUT / "browser_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
