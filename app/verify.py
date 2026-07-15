"""Option A: a verification pass that grounds each extracted line item in the
source email/attachment text.

This is deliberately simple and dependency-free: it's a defense against a
model that invents a part number, mis-transcribes digits, or -- as in the
rfq-07-restock sample -- gets talked into suppressing real line items by an
injected instruction. It never drops a line item; it only appends a warning
so a human reviewer sees the flag before the item reaches the ERP.
"""
from __future__ import annotations

import re

from .models import RfqExtraction


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def ground_check(extraction: RfqExtraction, source_text: str) -> RfqExtraction:
    haystack = _normalize(source_text)
    digits_only = re.sub(r"[^0-9]", "", source_text)

    warnings = list(extraction.warnings)

    for item in extraction.lineItems:
        part_norm = _normalize(item.partNumber)
        if part_norm and part_norm not in haystack:
            warnings.append(
                f"Part number '{item.partNumber}' was not found verbatim in the "
                "source email/attachment -- possible model hallucination or "
                "transcription error. Verify before quoting."
            )
        if item.quantity and str(item.quantity) not in digits_only:
            warnings.append(
                f"Quantity {item.quantity} for '{item.partNumber}' was not found "
                "verbatim in the source. If this is a computed value (e.g. "
                "per-board math) that's expected -- check the notes field. "
                "Otherwise it may be a transcription error."
            )

    extraction.warnings = warnings
    return extraction
