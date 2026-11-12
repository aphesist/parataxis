"""The paper page (site/index.html) is built by site/build.py from README.md and the study's analysis.json."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_site_page_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "site" / "build.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_site_page_links_only_its_own_files():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert 'href="vendor/lab-kit-v1/lab.css"' in html and 'src="vendor/lab-kit-v1/lab.js"' in html
    assert "<!--" + "HONESTY-->" not in html and "{n}" not in html and "title=" not in html
