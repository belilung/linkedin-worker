"""Import LinkedIn cookies from browser export (JSON format).

Usage:
  1. Install "EditThisCookie" or "Cookie-Editor" extension in your browser
  2. Go to linkedin.com while logged in
  3. Export all cookies as JSON
  4. Save the JSON to a file or paste it when prompted
  
  python3 import_cookies.py [cookies.json]
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path("data/cookies")
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT = DATA_DIR / "linkedin_cookies.json"


def convert_cookies(raw_cookies):
    """Convert browser extension format to Playwright format."""
    converted = []
    for c in raw_cookies:
        cookie = {
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain", ".linkedin.com"),
            "path": c.get("path", "/"),
        }
        if "expirationDate" in c:
            cookie["expires"] = c["expirationDate"]
        if "sameSite" in c:
            ss = c["sameSite"].lower()
            cookie["sameSite"] = {"lax": "Lax", "strict": "Strict", "none": "None"}.get(ss, "Lax")
        else:
            cookie["sameSite"] = "Lax"
        cookie["secure"] = c.get("secure", True)
        cookie["httpOnly"] = c.get("httpOnly", False)
        converted.append(cookie)
    return converted


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            raw = json.load(f)
    else:
        print("Paste your cookies JSON (then press Ctrl+D):")
        raw = json.load(sys.stdin)
    
    cookies = convert_cookies(raw)
    with open(OUTPUT, "w") as f:
        json.dump(cookies, f, indent=2)
    
    print(f"Saved {len(cookies)} cookies to {OUTPUT}")
    print("LinkedIn Worker should now be able to use these cookies.")


if __name__ == "__main__":
    main()
