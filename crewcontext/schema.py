"""Event schema validation using Pydantic.

Provides type-safe event validation with clear error messages.

Usage:
    from crewcontext.schema import EventSchema, ValidationError
    
    class InvoiceReceivedEvent(EventSchema):
        invoice_id: str
        vendor_id: str
        amount: float
        currency: str = "USD"
    
    ctx.register_event_schema("invoice.received", InvoiceReceivedEvent)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel, ConfigDict, ValidationError as PydanticValidationError

log = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when event data fails schema validation."""

    def __init__(self, event_type: str, errors: list[dict[str, Any]]):
        self.event_type = event_type
        self.errors = errors
        error_msgs = [f"{e['loc']}: {e['msg']}" for e in errors]
        super().__init__(
            f"Validation failed for event type '{event_type}': {'; '.join(error_msgs)}"
        )


class EventSchema(BaseModel):
    """Base class for event schemas.

    Subclass this to define your event schemas:

    class InvoiceReceivedEvent(EventSchema):
        invoice_id: str
        vendor_id: str
        amount: float
        currency: str = "USD"

        model_config = ConfigDict(extra="forbid")
    """

    model_config = ConfigDict(extra="ignore")  # Allow extra fields by default


class SchemaRegistry:
    """Registry for event schemas with validation.

    Thread-safe, supports runtime schema registration.
    """

    def __init__(self):
        self._schemas: Dict[str, Type[EventSchema]] = {}
        self._strict_mode: bool = False

    def register(
        self, event_type: str, schema: Type[EventSchema], strict: bool = None
    ) -> None:
        """Register a schema for an event type.

        Args:
            event_type: Dotted event name (e.g. "invoice.received").
            schema: Pydantic model class for validation.
            strict: If True, reject unknown fields (extra="forbid").
        """
        if strict is None:
            strict = self._strict_mode

        # Create a copy of the schema with strict mode if needed
        if strict:
            from pydantic import ConfigDict
            schema = type(
                schema.__name__,
                (schema,),
                {"model_config": ConfigDict(extra="forbid")},
            )

        self._schemas[event_type] = schema
        log.debug("Registered schema for event type: %s", event_type)

    def unregister(self, event_type: str) -> bool:
        """Remove a schema registration."""
        if event_type in self._schemas:
            del self._schemas[event_type]
            log.debug("Unregistered schema for event type: %s", event_type)
            return True
        return False

    def validate(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate event data against registered schema.

        Args:
            event_type: Dotted event name.
            data: Event data dictionary.

        Returns:
            Validated data (may be transformed by Pydantic).

        Raises:
            ValidationError: If validation fails.
        """
        schema = self._schemas.get(event_type)
        if schema is None:
            # No schema registered - pass through
            log.debug("No schema for event type %s, passing through", event_type)
            return data

        try:
            validated = schema(**data)
            return validated.model_dump()
        except PydanticValidationError as e:
            errors = [
                {"loc": err["loc"], "msg": err["msg"], "type": err["type"]}
                for err in e.errors()
            ]
            log.warning(
                "Validation failed for event type %s: %s",
                event_type,
                errors,
            )
            raise ValidationError(event_type, errors)

    def set_strict_mode(self, strict: bool) -> None:
        """Set global strict mode for all schemas.

        In strict mode, unknown fields are rejected.
        """
        self._strict_mode = strict
        log.info("Schema registry strict mode: %s", strict)

    def get_schema(self, event_type: str) -> Optional[Type[EventSchema]]:
        """Get the schema for an event type."""
        return self._schemas.get(event_type)

    def list_schemas(self) -> list[str]:
        """List all registered event types."""
        return list(self._schemas.keys())
