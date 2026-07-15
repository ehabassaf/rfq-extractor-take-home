from app.models import Customer, LineItem, RequestInfo, RfqExtraction
from app.verify import ground_check


def _extraction(line_items):
    return RfqExtraction(
        isRfq=True,
        confidence=0.9,
        customer=Customer(),
        request=RequestInfo(),
        lineItems=line_items,
        warnings=[],
    )


def test_grounded_part_and_quantity_produce_no_warning():
    source = "We need LM358N, quantity 500 please."
    extraction = _extraction([LineItem(partNumber="LM358N", quantity=500)])
    result = ground_check(extraction, source)
    assert result.warnings == []


def test_hallucinated_part_number_is_flagged():
    source = "We need LM358N, quantity 500 please."
    extraction = _extraction([LineItem(partNumber="XYZ9999", quantity=500)])
    result = ground_check(extraction, source)
    assert len(result.warnings) == 1
    assert "XYZ9999" in result.warnings[0]
    assert "not found verbatim" in result.warnings[0]


def test_mismatched_quantity_is_flagged():
    source = "We need LM358N, quantity 500 please."
    extraction = _extraction([LineItem(partNumber="LM358N", quantity=999)])
    result = ground_check(extraction, source)
    assert len(result.warnings) == 1
    assert "999" in result.warnings[0]


def test_zero_quantity_never_triggers_a_quantity_warning():
    source = "We need LM358N, no quantity given."
    extraction = _extraction([LineItem(partNumber="LM358N", quantity=0)])
    result = ground_check(extraction, source)
    assert result.warnings == []


def test_flags_never_drop_the_line_item():
    """Option A requires: flag, never silently drop."""
    source = "totally unrelated email content"
    extraction = _extraction([LineItem(partNumber="MADEUP123", quantity=42)])
    result = ground_check(extraction, source)
    assert len(result.lineItems) == 1
    assert result.lineItems[0].partNumber == "MADEUP123"
    assert len(result.warnings) == 2  # part not found + quantity not found
