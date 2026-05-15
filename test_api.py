"""Quick API verification script - install httpx first"""
import subprocess
import sys

# Install httpx in the venv if not present
subprocess.run([sys.executable, "-m", "pip", "install", "httpx"], capture_output=True)

import httpx

with open("doc1.docx", "rb") as f1, open("doc2.docx", "rb") as f2:
    files = [
        ("files", ("doc1.docx", f1, "application/octet-stream")),
        ("files", ("doc2.docx", f2, "application/octet-stream")),
    ]
    response = httpx.post("http://127.0.0.1:8000/api/analyze", files=files, timeout=30)

print("STATUS CODE:", response.status_code)
import json
data = response.json()
print(json.dumps(data, indent=2, ensure_ascii=False))
