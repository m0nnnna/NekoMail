"""Install pip into a venv created with --without-pip.

Ubuntu ships python3 without ensurepip unless python3-venv is installed (and
we never use sudo). This fetches the official pip wheel from PyPI, verifies
its sha256 against PyPI's own metadata, and installs it into the venv that is
running this script.

usage: <venv>/bin/python bootstrap_pip.py
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

meta = json.load(urllib.request.urlopen("https://pypi.org/pypi/pip/json", timeout=30))
for f in meta["urls"]:
    if f["filename"].endswith("-py3-none-any.whl"):
        break
else:
    sys.exit("no pip wheel found on PyPI")
data = urllib.request.urlopen(f["url"], timeout=60).read()
if hashlib.sha256(data).hexdigest() != f["digests"]["sha256"]:
    sys.exit("pip wheel sha256 mismatch")
with tempfile.TemporaryDirectory() as d:
    wheel = Path(d) / f["filename"]
    wheel.write_bytes(data)
    env = {"PYTHONPATH": str(wheel), "PATH": "/usr/bin:/bin"}
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", str(wheel)], env=env)
print("pip", meta["info"]["version"], "installed")
