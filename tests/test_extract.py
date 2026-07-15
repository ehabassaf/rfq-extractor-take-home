"""extract.py logic with the LLM mocked out -- no network calls, no API key
needed. Verifies the stub fallback, the happy path, and the two "the model
didn't behave" cases (refusal, schema mismatch)."""
from types import SimpleNamespace

from app import extract
from app.email_parse import ParsedEmail
from app.models import Customer, ExtractionWrapper, NotRfqExtraction, RequestInfo, RfqExtraction


def _parsed_email(body="Please quote LM358N qty 10"):
    return ParsedEmail(from_="a@b.com", to="sales@x.com", subject="RFQ", date="", body=body, attachments=[])


class _FakeMessages:
    def __init__(self, response):
        self._response = response

    def parse(self, **kwargs):
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def test_stub_result_when_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = extract.extract_rfq(_parsed_email())
    assert isinstance(result, NotRfqExtraction)
    assert "stubbed" in result.reason.lower()


def test_successful_extraction_returns_parsed_output(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    expected = RfqExtraction(
        isRfq=True,
        confidence=0.9,
        customer=Customer(name="Jane"),
        request=RequestInfo(),
        lineItems=[],
        warnings=[],
    )
    fake_response = SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=ExtractionWrapper(result=expected),
    )
    monkeypatch.setattr(extract, "_client", lambda: _FakeClient(fake_response))

    result = extract.extract_rfq(_parsed_email())
    assert isinstance(result, RfqExtraction)
    assert result.customer.name == "Jane"


def test_refusal_stop_reason_becomes_not_rfq(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_response = SimpleNamespace(stop_reason="refusal", parsed_output=None)
    monkeypatch.setattr(extract, "_client", lambda: _FakeClient(fake_response))

    result = extract.extract_rfq(_parsed_email())
    assert isinstance(result, NotRfqExtraction)
    assert "declined" in result.reason.lower()


def test_schema_mismatch_becomes_not_rfq(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_response = SimpleNamespace(stop_reason="end_turn", parsed_output=None)
    monkeypatch.setattr(extract, "_client", lambda: _FakeClient(fake_response))

    result = extract.extract_rfq(_parsed_email())
    assert isinstance(result, NotRfqExtraction)
    assert "schema" in result.reason.lower()
