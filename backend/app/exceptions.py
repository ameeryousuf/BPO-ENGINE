"""Custom exceptions for the BPO redesign engine.

These are translated into HTTP responses by the API layer (see
``app.api.redesign``), keeping the service and core layers free of any
HTTP-specific concerns.
"""


class BPOEngineError(Exception):
    """Base class for all domain errors raised by the redesign engine."""


class InvalidJSONError(BPOEngineError):
    """Raised when the uploaded payload is not valid JSON."""


class InvalidProcessDefinitionError(BPOEngineError):
    """Raised when parsed JSON does not describe a valid BPMN process."""


class RedesignIntegrityError(BPOEngineError):
    """Raised when replayed metrics do not match the metrics reported during training."""
