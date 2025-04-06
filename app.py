import os
import re
import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, request, jsonify, render_template, url_for
from playwright.sync_api import sync_playwright, Error as PlaywrightError

# --- Configuration ---
SCREENSHOT_DIR = Path("static") / "screenshots"
DEFAULT_TIMEOUT = 30000  # 30 seconds timeout for page load
# --- End Configuration ---

app = Flask(__name__)

# Ensure the screenshot directory exists
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

def sanitize_filename(url_str):
    """Creates a safe filename from a URL."""
    parsed_url = urlparse(url_str)
    domain = parsed_url.netloc or "local"
    path = parsed_url.path.strip('/')
    base_name = f"{domain}_{path}" if path else domain
    safe_name = re.sub(r'[^\w\-.]', '_', base_name)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    max_len = 100
    return f"{safe_name[:max_len]}_{timestamp}.png"

def normalize_url(url):
    """Adds https:// if scheme is missing."""
    url = url.strip()
    if not url:
        return None
    if not re.match(r'^[a-zA-Z]+://', url):
        return f'https://{url}'
    return url

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/screenshot', methods=['POST'])
def take_screenshots():
    data = request.get_json()
    if not data or 'urls' not in data:
        return jsonify({"error": "Missing 'urls' in request body"}), 400

    raw_urls = data.get('urls', [])
    results = []

    if not raw_urls:
        return jsonify(results)

    print(f"Received request for {len(raw_urls)} URLs.")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--ignore-certificate-errors",
                    "--allow-insecure-localhost",
                    "--no-sandbox"
                ]
            )
            print("Browser launched.")

            context = browser.new_context(ignore_https_errors=True)

            for raw_url in raw_urls:
                normalized_url = normalize_url(raw_url)
                if not normalized_url:
                    results.append({"url": raw_url, "status": "error", "message": "Invalid or empty URL"})
                    continue

                print(f"Processing: {normalized_url}")
                filename = sanitize_filename(normalized_url)
                save_path = SCREENSHOT_DIR / filename
                page = None

                try:
                    page = context.new_page()
                    page.goto(normalized_url, wait_until='load', timeout=DEFAULT_TIMEOUT)
                    page.screenshot(path=save_path, full_page=True)
                    page.close()
                    print(f"Success: {normalized_url} -> {filename}")
                    results.append({
                        "url": raw_url,
                        "status": "success",
                        "image_path": url_for('static', filename=f'screenshots/{filename}')
                    })
                except PlaywrightError as e:
                    error_message = str(e).splitlines()[0]
                    print(f"Error processing {normalized_url}: {error_message}")
                    results.append({"url": raw_url, "status": "error", "message": error_message})
                    if page and not page.is_closed():
                        page.close()
                except Exception as e:
                    print(f"Unexpected Error processing {normalized_url}: {e}")
                    results.append({"url": raw_url, "status": "error", "message": f"Unexpected error: {str(e)}"})
                    if page and not page.is_closed():
                        page.close()

            browser.close()
            print("Browser closed.")

    except Exception as e:
        print(f"General Playwright/Browser Error: {e}")
        if not results:
            for raw_url in raw_urls:
                results.append({"url": raw_url, "status": "error", "message": f"Browser setup failed: {str(e)}"})

    print("Processing complete. Sending results.")
    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
