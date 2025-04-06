# app.py
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
    # Use domain and path, replace unsafe characters
    domain = parsed_url.netloc or "local"
    path = parsed_url.path.strip('/')
    base_name = f"{domain}_{path}" if path else domain
    safe_name = re.sub(r'[^\w\-.]', '_', base_name)
    # Add timestamp to ensure uniqueness
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    # Limit length to avoid issues
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
    """Serves the main HTML page."""
    return render_template('index.html')

@app.route('/screenshot', methods=['POST'])
def take_screenshots():
    """API endpoint to handle screenshot requests."""
    data = request.get_json()
    if not data or 'urls' not in data:
        return jsonify({"error": "Missing 'urls' in request body"}), 400

    raw_urls = data.get('urls', [])
    results = []

    if not raw_urls:
        return jsonify(results) # Return empty list if no URLs provided

    print(f"Received request for {len(raw_urls)} URLs.")

    try:
        with sync_playwright() as p:
            # Use Chromium by default. Can also use p.firefox or p.webkit
            browser = p.chromium.launch(headless=False)
            print("Browser launched.")

            for raw_url in raw_urls:
                normalized_url = normalize_url(raw_url)
                if not normalized_url:
                    results.append({"url": raw_url, "status": "error", "message": "Invalid or empty URL"})
                    continue

                print(f"Processing: {normalized_url}")
                filename = sanitize_filename(normalized_url)
                save_path = SCREENSHOT_DIR / filename
                page = None # Initialize page to None

                try:
                    page = browser.new_page()
                    # Navigate to the page, wait for load state
                    page.goto(normalized_url, wait_until='load', timeout=DEFAULT_TIMEOUT)
                    # Take screenshot
                    page.screenshot(path=save_path, full_page=True) # Set full_page=False for viewport only
                    page.close()
                    print(f"Success: {normalized_url} -> {filename}")
                    results.append({
                        "url": raw_url,
                        "status": "success",
                        # Use url_for for correct path even if app is hosted differently
                        "image_path": url_for('static', filename=f'screenshots/{filename}')
                    })
                except PlaywrightError as e:
                    error_message = str(e)
                    # Try to extract a more concise error message
                    if "net::ERR_" in error_message:
                        error_message = error_message.splitlines()[0] # Often the first line is enough
                    elif "Timeout" in error_message:
                         error_message = f"Timeout ({DEFAULT_TIMEOUT/1000}s) exceeded while loading."

                    print(f"Error processing {normalized_url}: {error_message}")
                    results.append({"url": raw_url, "status": "error", "message": error_message})
                    if page and not page.is_closed():
                        page.close() # Ensure page is closed even on error
                except Exception as e: # Catch any other unexpected errors
                     print(f"Unexpected Error processing {normalized_url}: {e}")
                     results.append({"url": raw_url, "status": "error", "message": f"Unexpected error: {str(e)}"})
                     if page and not page.is_closed():
                        page.close()

            browser.close()
            print("Browser closed.")

    except Exception as e:
        # Catch errors during Playwright startup/shutdown
        print(f"General Playwright/Browser Error: {e}")
        # Add error indication for all URLs if the browser fails globally
        if not results: # If no results processed yet
             for raw_url in raw_urls:
                 results.append({"url": raw_url, "status": "error", "message": f"Browser setup failed: {str(e)}"})
        # Else, maybe add a general error message? Or rely on per-URL errors already logged.

    print("Processing complete. Sending results.")
    return jsonify(results)

if __name__ == '__main__':
    # Make sure to use 0.0.0.0 if you want to access it from other devices on your network
    # Use 127.0.0.1 (default) for strictly local access
    app.run(debug=True, host='127.0.0.1', port=5000)
    # Set debug=False for production use