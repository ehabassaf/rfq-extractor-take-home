# RFQ Data Ingestion

Turns a raw RFQ email into structured data ready for an ERP: parse the email
(including CSV/PDF attachments), decide whether it's actually a request for
quote, extract a structured requirement with an LLM, expose it over HTTP, and
show it in a small dashboard.

## How to run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
# (optional) override RFQ_MODEL — defaults to claude-sonnet-5, a good
# cost/quality balance for structured extraction; claude-opus-4-8 if you
# want the most capable model regardless of cost, claude-haiku-4-5 if you
# want the cheapest/fastest option

uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/` for the dashboard. It has a small upload box to
test `POST /ingest` with any of the sample `.eml` files, plus a live table of
everything ingested so far.

To exercise the whole sample set at once and diff the 5 labeled emails
against the hand-checked answers in `samples/labels.json`:

```bash
python scripts/run_samples.py
```

Run the test suite (fast, no API key needed — the LLM is mocked):

```bash
pytest
```

**No API key?** The service still runs. `extract.py` falls back to a
clearly-labeled stub result (`isRfq: false`, reason explains why) so parsing,
the HTTP endpoints, and the dashboard all work end to end — per the spec's
"stub the call" allowance. Real classification/extraction needs a key.

## The API

`POST /ingest` — body is the raw email, either as `Content-Type:
message/rfc822` / `text/plain` bytes, or as a multipart file upload under
the field name `file`. Returns the JSON contract from the spec.

`GET /rfqs` — summary list backing the dashboard table.
`GET /rfqs/{id}` — full detail for one ingested email.

## Architecture

See [`architecture/README.md`](architecture/README.md) for a diagram of the
request flow and a file-by-file breakdown. Quick file map:

```
app/
  main.py          FastAPI: POST /ingest, GET /rfqs, GET /rfqs/{id}, dashboard
  models.py         Pydantic models = the output contract (source of truth for shape)
  email_parse.py    MIME walk, attachment decode (CSV/PDF/image); no LLM involved
  prompts.py        System prompt + per-email user prompt
  extract.py        The one LLM call, via structured outputs
  verify.py         Option A: grounds each line item in the source text
  store.py          In-memory store (no DB, per spec)
  static/index.html Dashboard (plain HTML/CSS/JS, no build step)
scripts/run_samples.py   Ingests every sample, diffs the 5 labeled ones
tests/                    Deterministic tests; LLM is mocked, no network calls
```

Data flow: `raw .eml -> email_parse.parse_eml() -> ParsedEmail(body,
attachments, source_text) -> extract.extract_rfq() -> Pydantic-validated
result -> verify.ground_check() appends warnings -> store -> HTTP/dashboard`.

## Key decisions and why

**Structured outputs over hand-rolled JSON prompting.** The whole point of
the exercise is "getting a model to reliably produce data in this shape,
every time." Rather than asking the model to emit JSON and hoping, `extract.py`
calls `client.messages.parse(..., output_format=ExtractionWrapper)` where
`ExtractionWrapper` *is* the Pydantic model for the contract (`models.py`).
The API enforces the schema at generation time and hands back a validated
Python object — there's no brittle "please respond only with JSON" prompt, no
manual `json.loads()` + schema-check, and no chance of a stray sentence
polluting the output. The two possible shapes (`isRfq: true` vs `false`) are
expressed as a `Union` nested under a wrapper object, since structured
outputs need a single top-level schema.

**Reliability failure modes are handled explicitly, not left to crash.** Three
things can go wrong with an LLM call in production and each gets a specific,
labeled fallback rather than an unhandled exception reaching the caller:
an API error (network/5xx/429), a safety-classifier `refusal` (a valid HTTP
200 the code must check for before touching the response body), and a
schema mismatch (`parsed_output is None`). All three degrade to
`isRfq: false` with a `reason` explaining exactly what happened, so a human
sees "this needs manual review" instead of a 500.

**Prompt-injection defense is not optional.** `rfq-07-restock.eml` contains a
real attack: a block of text formatted to look like a system instruction,
telling the model to claim the email isn't an RFQ and to hide that it was
told to. The defense is layered:
1. The system prompt (`prompts.py`) explicitly states that email content is
   untrusted data to extract information *from*, never instructions to
   follow, and that any manipulation attempt should be surfaced as a warning
   rather than obeyed.
2. The user-turn wraps the email in `<untrusted_email_content>` delimiters.
3. Defense in depth: even if the model were talked into misclassifying the
   email or dropping line items, the verification pass (below) grounds every
   line item against the source text and would flag missing/invented parts.

**Verification pass (Option A) grounds every line item.** After extraction,
`verify.ground_check()` checks that each `partNumber` and non-zero `quantity`
actually appears (case/whitespace-normalized) in the email body + decoded
attachments. A miss appends a warning — it never drops the item. This catches
two distinct failure modes with one mechanism: a model that invents or
mis-transcribes a part, and the injection scenario above (if the model had
listened to the injected instruction and only reported some of the real
parts, the ones it dropped would simply never have been extracted in the
first place — so the more interesting check here is that all *three* real
parts in `rfq-07` show up despite the injection).

**Judgment calls on genuine ambiguity, encoded as conventions.** The spec
calls out several samples with no single correct answer. Rather than
guessing silently, the prompt states a specific, consistent convention for
each and asks the model to surface the ambiguity via `warnings`/`notes`:
- **Quantity ranges** (`rfq-03-ambiguous`, e.g. "100-150 units", "approx.
  100"): commit the *lower* bound to `quantity` (conservative — never
  over-promise availability), preserve the original phrasing in `notes`, add
  a top-level warning. A human can always requote a range; a distributor
  that silently quotes the high end and can't deliver is worse.
- **Per-board/per-unit math** (`rfq-06-multi-project`, e.g. "2 per board, 500
  boards"): compute the total, record the arithmetic in `notes`, flag it as
  computed. The alternative — leaving `quantity` as the per-unit figure — is
  actively wrong for pricing/ordering purposes.
- **Manufacturer aliases** ("TI", "ON Semi"): resolved to full names only
  when the prompt is confident of the mapping; never guessed.
- **Split body/attachment** (`rfq-05-pdf-attachment`): the NEO-6M GPS module
  is mentioned only in the email body, not the attached PDF. `source_text`
  concatenates body + all attachment text before it ever reaches the model,
  so this merges naturally rather than needing special-case code.
- **Image attachment** (`rfq-08-image`): `email_parse.py` can't extract text
  from a scanned PNG (Option B/vision was not implemented — see below). The
  prompt is told to expect this and return `isRfq: true` with an empty
  `lineItems`, low confidence, and an explicit warning, rather than guessing
  at parts it can't see or silently failing.

**No database, in-memory store.** Per the spec's explicit non-goal. `store.py`
is a module-level list; fine for a single-process demo, explicitly not
meant to survive a restart or handle concurrent writers.

**Dashboard is one static HTML file, no build step.** A founding-engineer
take-home is judged partly on "would I want to live with this code" — a
15-minute demo doesn't need webpack. Plain HTML/CSS/vanilla JS, fetches
`/rfqs` and `/rfqs/{id}` directly.

## What I would do with more time

- **Option B (vision for the scanned image).** `rfq-08-image.eml`'s PNG has
  no text layer. The natural extension is to pass the image bytes as a
  `{"type": "image", "source": {"type": "base64", ...}}` content block
  alongside the text prompt to a vision-capable Claude call — the plumbing
  for this is a small, contained addition to `extract.py` (a separate
  code path when an image attachment is present and no other line items
  were found), but I scoped it out to stay inside the time budget.
- **Option C — catalog normalization.** `samples/parts-catalog.csv` maps
  messy part numbers/manufacturer shorthand to canonical entries. A
  `lookup_part` tool the model could call during extraction (or a
  post-extraction fuzzy-match pass) would resolve `"BC547 transistor"` to
  the catalog's `BC547 / ON Semiconductor / NPN transistor TO-92` entry and
  attach a `catalogMatch` field — useful for the ERP, out of scope here.
- **Retry-on-validation-failure.** Right now a schema mismatch or refusal
  degrades straight to a flagged `isRfq: false`. A single retry with the
  validation error appended to the prompt would likely resolve transient
  misses without giving up on the email entirely.
- **Provenance.** Each line item pointing back to the exact source span it
  came from (e.g. via citations on the `document`/`text` content blocks)
  would make the human-review step in the dashboard much faster to audit.
- **Smarter grounding for computed quantities.** `verify.py`'s digit-match
  check is intentionally simple; it can't confirm "1000" is really "2 per
  board x 500 boards" beyond checking the model said so in `notes`. A
  stricter check would parse the arithmetic out of `notes` and re-derive it.
- **Persist across restarts.** A single JSON-lines file would be enough
  (spec explicitly says a DB isn't required) and would survive `--reload`.

## Time spent

Roughly 4 hours: ~30 min reading samples/spec and identifying the judgment
calls the samples actually test (ranges, per-board math, split
body/attachment, the injection attempt), ~45 min on architecture/plan, ~2
hours building (parsing, structured-outputs extraction, verification,
FastAPI, dashboard, tests), ~45 min on this README and end-to-end
verification.
