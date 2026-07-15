"""Pydantic models for the RFQ output contract.

These models are the single source of truth for the JSON shape described in
the spec: they double as the schema handed to the LLM via structured outputs
(`output_format=ExtractionWrapper` in extract.py) and as the validator for
whatever comes back. If the model produces something that doesn't fit these
types, `messages.parse()` will not return a `parsed_output` at all — see
extract.py for how that failure is handled.
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Customer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None


class RequestInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dueDate: Optional[str] = Field(
        default=None, description="YYYY-MM-DD, or null if not stated"
    )
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    specialInstructions: Optional[str] = None


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partNumber: str
    manufacturer: Optional[str] = None
    description: Optional[str] = None
    quantity: int = 0
    targetPrice: Optional[float] = None
    notes: Optional[str] = None


class RfqExtraction(BaseModel):
    """Shape for isRfq=true."""

    model_config = ConfigDict(extra="forbid")

    isRfq: Literal[True]
    confidence: float
    customer: Customer
    request: RequestInfo
    lineItems: list[LineItem]
    warnings: list[str] = Field(default_factory=list)


class NotRfqExtraction(BaseModel):
    """Shape for isRfq=false."""

    model_config = ConfigDict(extra="forbid")

    isRfq: Literal[False]
    confidence: float
    reason: str


class ExtractionWrapper(BaseModel):
    """Wrapper passed as `output_format` to `client.messages.parse()`.

    Structured outputs need a single model class, not a bare Union, so the
    two possible result shapes are nested under `result`. The Union itself
    (no discriminator) is enough for Pydantic to validate against whichever
    branch matches the `isRfq` literal the model returned.
    """

    model_config = ConfigDict(extra="forbid")

    result: Union[RfqExtraction, NotRfqExtraction]


IngestResult = Union[RfqExtraction, NotRfqExtraction]
