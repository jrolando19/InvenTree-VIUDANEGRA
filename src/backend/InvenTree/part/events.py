"""Event definitions and triggers for the part app."""

# Nota: modulo sin importadores en todo el repo (confirmado via grep) -- codigo
# muerto, nunca se importa ni ejecuta.
from generic.events import BaseEventEnum  # pragma: no cover


class PartEvents(BaseEventEnum):  # pragma: no cover
    """Event enumeration for the Part models."""
