import json
import logging

import pytest

from banco_agil.models.responses import FallbackReason
from banco_agil.observability import Event, record

SESSION = "66b2cfe5-c9ab-435e-bdcf-e0b0880d2f50"


@pytest.mark.parametrize("field", ["agent", "status", "error_code", "reason", "session_id"])
@pytest.mark.parametrize("unsafe", ["CPF 00000000001, Ana, R$ 1.000,00", {"prompt": "private"}])
def test_record_rejects_unclassified_content(field, unsafe, caplog):
    caplog.set_level(logging.INFO, logger="banco_agil")
    arguments = {"session_id": SESSION, field: unsafe}
    with pytest.raises((TypeError, ValueError)):
        record(Event.OPERATION_FAILED, **arguments)
    assert not caplog.records


@pytest.mark.parametrize("field", ["message", "prompt", "value", "payload"])
def test_record_rejects_arbitrary_payload_fields(field, caplog):
    with pytest.raises(TypeError):
        record(Event.OPERATION_FAILED, SESSION, **{field: "private"})
    assert not caplog.records


def test_record_serializes_only_closed_metadata(caplog):
    caplog.set_level(logging.INFO, logger="banco_agil")
    record(
        Event.OPERATION_FAILED,
        SESSION,
        agent="credit",
        status="rejeitado",
        error_code="invalid_llm_output",
        reason=FallbackReason.INVALID_SCHEMA,
    )
    assert json.loads(caplog.records[0].message) == {
        "event": "operation_failed",
        "session_id": SESSION,
        "agent": "credit",
        "status": "rejeitado",
        "error_code": "invalid_llm_output",
        "reason": "invalid_schema",
    }
