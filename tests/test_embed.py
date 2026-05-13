import http.server
import os
import shutil
import socketserver
import threading
import time

import pytest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8765


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


class _ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


@pytest.fixture(scope="module")
def server():
    os.chdir(ROOT)
    httpd = _ReusableTCPServer(("127.0.0.1", PORT), _SilentHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    yield f"http://127.0.0.1:{PORT}"
    httpd.shutdown()


def _swap_data(name):
    shutil.copy(
        os.path.join(ROOT, "tests", "fixtures", name),
        os.path.join(ROOT, "data", "prices.json"),
    )


def test_embed_renders_cards_and_map(server):
    _swap_data("prices-fresh.json")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{server}/embed.html?v=fresh")
        page.wait_for_selector("#content:not([hidden])", timeout=5000)
        assert page.locator(".card").count() == 3
        assert "$" in page.locator(".cheapest .price").inner_text()
        page.wait_for_selector(".county")
        assert page.locator(".county").count() == 16
        assert page.locator("#stale").is_hidden()
        browser.close()


def test_embed_shows_stale_warning(server):
    _swap_data("prices-stale.json")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{server}/embed.html?v=stale")
        page.wait_for_selector("#stale:not([hidden])", timeout=5000)
        assert "last updated" in page.locator("#stale").inner_text().lower()
        browser.close()
