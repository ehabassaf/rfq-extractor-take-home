"""FastAPI service: POST /ingest turns a raw email into the structured
contract; GET /rfqs and /rfqs/{id} back the dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .email_parse import parse_eml
from .extract import extract_rfq
from .models import RfqExtraction
from .store import add_record, get_record, list_records
from .verify import ground_check

app = FastAPI(title="RFQ Extractor", description="RFQ Data Ingestion take-home")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/architecture")
def architecture() -> FileResponse:
    return FileResponse(STATIC_DIR / "architecture.html")


@app.post("/ingest")
async def ingest(request: Request, file: Optional[UploadFile] = File(None)):
    """Accepts the contents of one email, either as a raw request body
    (Content-Type: message/rfc822 or text/plain) or as a multipart file
    upload under the field name "file". Returns the structured contract."""
    if file is not None:
        raw = await file.read()
        filename = file.filename or "upload.eml"
    else:
        raw = await request.body()
        filename = request.headers.get("x-filename", "upload.eml")

    if not raw:
        raise HTTPException(status_code=400, detail="No email content provided")

    try:
        parsed = parse_eml(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse email: {e}")

    extraction = extract_rfq(parsed)

    if isinstance(extraction, RfqExtraction):
        extraction = ground_check(extraction, parsed.source_text)

    add_record(filename, extraction)
    return JSONResponse(extraction.model_dump())


@app.get("/rfqs")
def rfqs() -> list[dict]:
    """Summary list for the dashboard's main table."""
    out = []
    for r in list_records():
        d = r.result.model_dump()
        is_rfq = d["isRfq"]
        out.append(
            {
                "id": r.id,
                "filename": r.filename,
                "receivedAt": r.receivedAt,
                "isRfq": is_rfq,
                "confidence": d["confidence"],
                "customer": d.get("customer") if is_rfq else None,
                "priority": d.get("request", {}).get("priority") if is_rfq else None,
                "dueDate": d.get("request", {}).get("dueDate") if is_rfq else None,
                "lineItemCount": len(d.get("lineItems", [])) if is_rfq else 0,
                "warningCount": len(d.get("warnings", [])) if is_rfq else 0,
                "reason": d.get("reason") if not is_rfq else None,
            }
        )
    return out


@app.get("/rfqs/{record_id}")
def rfq_detail(record_id: int) -> dict:
    record = get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "id": record.id,
        "filename": record.filename,
        "receivedAt": record.receivedAt,
        **record.result.model_dump(),
    }
