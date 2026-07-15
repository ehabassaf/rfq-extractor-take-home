"""Deterministic, LLM-free parsing of raw .eml bytes.

Walks the MIME tree, pulls the plain-text body, and decodes attachments by
content type (CSV -> text, PDF -> extracted text via pypdf, image -> flagged
as unreadable in this build). Everything here is plain Python — no network
calls, no model calls — so it's fast, testable, and deterministic.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import Message

from pypdf import PdfReader


@dataclass
class Attachment:
    filename: str
    content_type: str
    text: str | None  # decoded/extracted text, or None if not extractable
    note: str | None = None  # e.g. "no text layer", "unsupported type"


@dataclass
class ParsedEmail:
    from_: str
    to: str
    subject: str
    date: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def source_text(self) -> str:
        """Body + all decoded attachment text, used both as the LLM's input
        and as the grounding corpus for the post-extraction verification
        pass (see verify.py)."""
        parts = [self.body]
        for a in self.attachments:
            if a.text:
                parts.append(
                    f"\n--- Attachment: {a.filename} ({a.content_type}) ---\n{a.text}"
                )
            elif a.note:
                parts.append(
                    f"\n--- Attachment: {a.filename} ({a.content_type}) — {a.note} ---"
                )
        return "\n".join(parts)


def parse_eml(raw: bytes) -> ParsedEmail:
    msg = message_from_bytes(raw, policy=policy.default)

    from_ = str(msg.get("From", ""))
    to = str(msg.get("To", ""))
    subject = str(msg.get("Subject", ""))
    date = str(msg.get("Date", ""))

    body = ""
    attachments: list[Attachment] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            filename = part.get_filename()

            is_attachment = disposition == "attachment" or (
                filename is not None and content_type != "text/plain"
            )
            if is_attachment:
                attachments.append(_extract_attachment(part, filename or "attachment", content_type))
            elif content_type == "text/plain" and not body:
                body = _get_text(part)
    else:
        if msg.get_content_type() == "text/plain":
            body = _get_text(msg)

    return ParsedEmail(
        from_=from_, to=to, subject=subject, date=date,
        body=body.strip(), attachments=attachments,
    )


def _get_text(part: Message) -> str:
    try:
        content = part.get_content()
        return content if isinstance(content, str) else str(content)
    except Exception:
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")


def _extract_attachment(part: Message, filename: str, content_type: str) -> Attachment:
    payload = part.get_payload(decode=True)
    if payload is None:
        return Attachment(filename, content_type, None, note="empty attachment payload")

    lower_name = filename.lower()

    if content_type == "text/csv" or lower_name.endswith(".csv"):
        try:
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception as e:
            return Attachment(filename, content_type, None, note=f"failed to decode CSV: {e}")
        return Attachment(filename, content_type, text)

    if content_type == "application/pdf" or lower_name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(payload))
            text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception as e:
            return Attachment(filename, content_type, None, note=f"failed to parse PDF: {e}")
        if not text:
            return Attachment(
                filename, content_type, None,
                note="PDF has no extractable text layer (likely a scanned image)",
            )
        return Attachment(filename, content_type, text)

    if content_type.startswith("image/"):
        return Attachment(
            filename, content_type, None,
            note=(
                "image attachment with no text layer — vision extraction is not "
                "enabled in this build (see README 'what's next')"
            ),
        )

    return Attachment(
        filename, content_type, None,
        note=f"unsupported attachment type ({content_type}); not extracted",
    )
