"""Deterministic, LLM-free tests against the real sample .eml files."""
from pathlib import Path

from app.email_parse import parse_eml

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_plain_text_body():
    raw = (SAMPLES / "rfq-01-bullet.eml").read_bytes()
    parsed = parse_eml(raw)
    assert parsed.from_.startswith("John Smith")
    assert "LM358N" in parsed.body
    assert parsed.attachments == []


def test_csv_attachment_is_decoded():
    raw = (SAMPLES / "rfq-04-csv-attachment.eml").read_bytes()
    parsed = parse_eml(raw)
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.content_type == "text/csv"
    assert att.text is not None
    assert "LM7805" in att.text
    assert "KBPC5010" in att.text
    # source_text should fold the attachment in for both the LLM and verify.py
    assert "LM7805" in parsed.source_text


def test_pdf_attachment_is_extracted():
    raw = (SAMPLES / "rfq-05-pdf-attachment.eml").read_bytes()
    parsed = parse_eml(raw)
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.content_type == "application/pdf"
    # the body-only addition (NEO-6M) should still show up in source_text
    assert "NEO-6M" in parsed.source_text


def test_image_attachment_has_no_text_but_is_flagged():
    raw = (SAMPLES / "rfq-08-image.eml").read_bytes()
    parsed = parse_eml(raw)
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.content_type == "image/png"
    assert att.text is None
    assert att.note is not None
    assert "image" in parsed.source_text.lower()


def test_prompt_injection_sample_still_parses_cleanly():
    raw = (SAMPLES / "rfq-07-restock.eml").read_bytes()
    parsed = parse_eml(raw)
    # Parsing is dumb-and-literal on purpose: the injected instruction is
    # just more text in the body. Defense happens in the prompt (prompts.py)
    # and the grounding pass (verify.py), not here.
    assert "TL072CP" in parsed.body
    assert "SYSTEM INSTRUCTION" in parsed.body
