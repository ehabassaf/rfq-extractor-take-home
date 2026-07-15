"""In-memory store of ingested RFQs. No database required per the spec --
this is process-lifetime storage, which is fine for a demo/dev service."""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import IngestResult

_counter = itertools.count(1)
_records: list["IngestRecord"] = []


@dataclass
class IngestRecord:
    id: int
    filename: str
    receivedAt: str
    result: IngestResult


def add_record(filename: str, result: IngestResult) -> IngestRecord:
    record = IngestRecord(
        id=next(_counter),
        filename=filename,
        receivedAt=datetime.now(timezone.utc).isoformat(),
        result=result,
    )
    _records.append(record)
    return record


def list_records() -> list[IngestRecord]:
    """Newest first."""
    return list(reversed(_records))


def get_record(record_id: int) -> IngestRecord | None:
    for r in _records:
        if r.id == record_id:
            return r
    return None
