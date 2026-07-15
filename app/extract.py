"""LLM-backed extraction: turns a ParsedEmail into an isRfq true/false result.

Reliability strategy: rather than free-form JSON prompting, this uses the
Claude API's structured-outputs feature (`output_format=` on
`client.messages.parse()`). The Pydantic models in models.py *are* the JSON
schema handed to the model, so the response is guaranteed to validate against
the exact output contract -- there is no brittle "please return JSON" prompt
and no manual json.loads() + schema-check dance.

If ANTHROPIC_API_KEY is not set, extraction falls back to a clearly-labeled
stub result so the rest of the service (parsing, HTTP, dashboard) still runs
end to end, per the spec's "stub the call" allowance.
"""
from __future__ import annotations

import os

import anthropic
from anthropic import Anthropic

from .email_parse import ParsedEmail
from .models import ExtractionWrapper, IngestResult, NotRfqExtraction
from .prompts import SYSTEM_PROMPT, build_user_prompt

DEFAULT_MODEL = os.environ.get("RFQ_MODEL", "claude-sonnet-5")


def _client() -> Anthropic | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return Anthropic()


def _stub_result() -> IngestResult:
    return NotRfqExtraction(
        isRfq=False,
        confidence=0.0,
        reason=(
            "ANTHROPIC_API_KEY is not set, so this is a stubbed result rather "
            "than a real extraction. Set the environment variable and "
            "re-ingest this email to get an actual classification."
        ),
    )


def extract_rfq(parsed: ParsedEmail) -> IngestResult:
    client = _client()
    if client is None:
        return _stub_result()

    try:
        response = client.messages.parse(
            model=DEFAULT_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(parsed)}],
            output_format=ExtractionWrapper,
        )
    except anthropic.APIStatusError as e:
        return NotRfqExtraction(
            isRfq=False,
            confidence=0.0,
            reason=(
                f"LLM API error during extraction (HTTP {e.status_code}); "
                "flagged for human review rather than guessed at."
            ),
        )
    except anthropic.APIConnectionError as e:
        return NotRfqExtraction(
            isRfq=False,
            confidence=0.0,
            reason=f"Network error calling the LLM ({e}); flagged for human review.",
        )

    # A safety-classifier refusal is a valid HTTP 200 with empty/partial
    # content -- must be checked before touching parsed_output.
    if response.stop_reason == "refusal":
        return NotRfqExtraction(
            isRfq=False,
            confidence=0.0,
            reason="Model declined to process this email content; flagged for human review.",
        )

    parsed_output = response.parsed_output
    if parsed_output is None:
        return NotRfqExtraction(
            isRfq=False,
            confidence=0.0,
            reason=(
                "Model output did not match the required schema "
                f"(stop_reason={response.stop_reason}); flagged for human review."
            ),
        )

    return parsed_output.result
