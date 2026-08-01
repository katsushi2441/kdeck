from __future__ import annotations

import os

from playwright.sync_api import sync_playwright


url = os.environ.get("KDECK_TEST_URL", "http://127.0.0.1:18308/kdeck.php")
errors: list[str] = []

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(url, wait_until="networkidle")
    assert page.evaluate("window.scrollY") == 0

    assert page.locator("#target-agent").input_value() == "local"
    folders = page.locator("#local-cwd option").evaluate_all("options => options.map(option => option.value)")
    for expected in ("/home/kojima/work/kfreqai", "/home/kojima/work/kmontage", "/home/kojima/work/OpenAlice-JP"):
        assert expected in folders

    backends = page.locator("#remote-llm-backend option").evaluate_all("options => options.map(option => option.value)")
    assert backends == ["auto", "codex-cli", "claude-cli"]
    assert "Claude Code" in page.locator("#remote-llm-backend option[value='claude-cli']").inner_text()

    models = page.locator("#chat-model option").evaluate_all("options => options.map(option => option.value)")
    assert models == ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]

    page.locator("#remote-llm-backend").select_option("claude-cli")
    assert page.locator("#remote-model").is_visible()
    assert page.locator("#remote-model").input_value() == "sonnet"
    assert not page.locator("#codex-model-row").is_visible()
    assert "OAuth" in page.locator("#llm-note").inner_text()

    dimensions = page.evaluate("({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})")
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"] + 1
    page.screenshot(path="/tmp/kdeck-mobile-smoke.png", full_page=False)
    browser.close()

assert not errors, errors
print("mobile_ui_smoke=ok")
