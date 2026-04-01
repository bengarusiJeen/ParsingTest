"""
ocr.py
------
Azure Document Intelligence (prebuilt-read) integration.

Used in the pre-test phase: for every imgX.png found inside a GT/ folder,
check whether descX.txt already exists — if not, run OCR and create it.

Environment variables required (.env or shell):
    AZURE_OCR_KEY       subscription key
    AZURE_OCR_ENDPOINT  e.g. https://<resource>.cognitiveservices.azure.com
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()


# ══════════════════════════════════════════════
# Azure OCR
# ══════════════════════════════════════════════

def run_ocr(image_path: Path) -> str:
    """
    Send an image to Azure Document Intelligence and return extracted text.
    Uses async polling: POST → 202 → poll Operation-Location until succeeded.
    """
    api_key  = os.getenv("AZURE_OCR_KEY")
    endpoint = os.getenv("AZURE_OCR_ENDPOINT", "").rstrip("/")

    if not api_key or not endpoint:
        raise RuntimeError("Missing AZURE_OCR_KEY or AZURE_OCR_ENDPOINT in .env")

    url     = (
        f"{endpoint}/documentintelligence/documentModels/"
        f"prebuilt-read:analyze?api-version=2024-11-30"
    )
    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "Content-Type": "application/octet-stream",
    }

    with open(image_path, "rb") as f:
        response = requests.post(url, headers=headers, data=f)
    response.raise_for_status()

    operation_url = response.headers["Operation-Location"]
    poll_headers  = {"Ocp-Apim-Subscription-Key": api_key}

    while True:
        result = requests.get(operation_url, headers=poll_headers).json()
        status = result.get("status")
        if status == "succeeded":
            break
        if status == "failed":
            raise RuntimeError(f"OCR job failed for {image_path.name}: {result}")
        time.sleep(1)

    lines = [
        line["content"]
        for page in result["analyzeResult"]["pages"]
        for line in page["lines"]
    ]
    return "\n".join(lines)


def _generate_desc(image_path: Path, desc_path: Path) -> None:
    """Run OCR on image_path and write the extracted text to desc_path."""
    print(f"[OCR] Processing: {image_path.name} ...", end=" ", flush=True)
    try:
        text = run_ocr(image_path).strip()
    except Exception as exc:
        print(f"FAILED ({exc})")
        return

    if not text:
        text = f"[WARNING] OCR returned no text for {image_path.name}"

    desc_path.write_text(text, encoding="utf-8")
    print(f"OK  →  {desc_path.name}")


# ══════════════════════════════════════════════
# Pre-test entry point
# ══════════════════════════════════════════════

def pre_test(input_dir: Path) -> None:
    """
    For every document subfolder in input_dir, scan its GT/ directory.
    For each imgX.png found, generate descX.txt via OCR if it is missing.
    """
    print("[i] Running Pre-Test (OCR description check)...\n")

    for doc_dir in sorted(input_dir.iterdir()):
        if not doc_dir.is_dir():
            continue

        gt_dir = doc_dir / "GT"
        if not gt_dir.is_dir():
            continue

        img_files = sorted(gt_dir.glob("img*.png"))
        if not img_files:
            continue

        print(f"  [{doc_dir.name}]")
        for img in img_files:
            number    = img.stem[3:]                  # "img3" → "3"
            desc_path = gt_dir / f"desc{number}.txt"

            if desc_path.exists():
                print(f"    [✓] {desc_path.name} already exists — skipping")
            else:
                _generate_desc(img, desc_path)
        print()

    print("[i] Pre-Test complete.\n")