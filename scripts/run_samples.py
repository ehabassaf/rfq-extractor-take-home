#!/usr/bin/env python3
"""Ingest every sample .eml through the real pipeline (parse -> extract ->
verify) and print the result. For the 5 emails with hand-checked answers in
samples/labels.json, diff the extraction against the label so discrepancies
are obvious at a glance.

Run from the project root:
    python scripts/run_samples.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.email_parse import parse_eml
from app.extract import extract_rfq
from app.models import RfqExtraction
from app.verify import ground_check

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "samples"
LABELS_PATH = SAMPLES_DIR / "labels.json"


def diff_against_label(filename: str, result: dict, label: dict) -> list[str]:
    diffs = []
    if result["isRfq"] != label["isRfq"]:
        diffs.append(f"isRfq: got {result['isRfq']}, expected {label['isRfq']}")
        return diffs

    if not label["isRfq"]:
        return diffs  # only isRfq/reason are checked for non-RFQs

    exp_customer = label.get("customer", {})
    got_customer = result.get("customer", {})
    for field in ("name", "email", "phone", "company"):
        if exp_customer.get(field) != got_customer.get(field):
            diffs.append(
                f"customer.{field}: got {got_customer.get(field)!r}, "
                f"expected {exp_customer.get(field)!r}"
            )

    exp_items = {i["partNumber"].strip().lower(): i for i in label.get("lineItems", [])}
    got_items = {i["partNumber"].strip().lower(): i for i in result.get("lineItems", [])}

    missing = set(exp_items) - set(got_items)
    extra = set(got_items) - set(exp_items)
    if missing:
        diffs.append(f"missing line items: {sorted(missing)}")
    if extra:
        diffs.append(f"unexpected extra line items: {sorted(extra)}")

    for part in exp_items.keys() & got_items.keys():
        exp_q = exp_items[part].get("quantity")
        got_q = got_items[part].get("quantity")
        if exp_q != got_q:
            diffs.append(f"{part}: quantity got {got_q}, expected {exp_q}")

    return diffs


def main() -> None:
    labels = json.loads(LABELS_PATH.read_text()) if LABELS_PATH.exists() else {}

    eml_files = sorted(SAMPLES_DIR.glob("*.eml"))
    if not eml_files:
        print(f"No .eml files found in {SAMPLES_DIR}")
        return

    total_diffs = 0
    for path in eml_files:
        raw = path.read_bytes()
        parsed = parse_eml(raw)
        extraction = extract_rfq(parsed)
        if isinstance(extraction, RfqExtraction):
            extraction = ground_check(extraction, parsed.source_text)
        result = extraction.model_dump()

        print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")
        print(json.dumps(result, indent=2))

        label = labels.get(path.name)
        if label is not None:
            diffs = diff_against_label(path.name, result, label)
            if diffs:
                total_diffs += len(diffs)
                print(f"\n  vs labels.json -- {len(diffs)} discrepancy(ies):")
                for d in diffs:
                    print(f"    - {d}")
            else:
                print("\n  vs labels.json -- matches.")

    print(f"\n{'=' * 70}")
    print(f"Done. {len(eml_files)} emails ingested; {total_diffs} discrepancies vs labels.json.")
    if not labels:
        print("(no labels.json found or it was empty)")


if __name__ == "__main__":
    main()
