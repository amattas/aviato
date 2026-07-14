from __future__ import annotations


class AviatoError(Exception):
    """Base class for all core engine errors."""


class PathConfinementError(AviatoError):
    """A filesystem operation would escape its trusted root."""


class CompositionError(AviatoError):
    """A profile/bundle could not be resolved or composed (§5.1, §4.2)."""


class DeclarationError(AviatoError):
    """A consumer declaration or variable set is invalid (§6.1, §6.6)."""


class MarkerError(AviatoError):
    """A managed marker could not be rendered or parsed (§6.2)."""


class InventoryError(AviatoError):
    """Managed inventory or marker-universe state could not be trusted."""


class AuthorizationError(AviatoError):
    """An authorization decision denied a privileged action (§5.8)."""


class CompatibilityError(AviatoError):
    """A version pin is incompatible with the acting tool (§2.6)."""


class BootstrapError(AviatoError):
    """A bootstrap declaration was used outside the Library (§5.10)."""
