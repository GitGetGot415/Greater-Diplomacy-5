"""Small numeric normalizers shared by rules that use bounded values.

Keep conversion policy explicit at the call site: ``clamp`` preserves a
numeric value's type, while ``clamp_float`` is for persisted/user supplied
values that must be safely coerced first.  Game-rule-specific rounding still
belongs with that rule (for example, the politics axis rounds to integers).
"""


def clamp(value, minimum, maximum):
    """Limits a comparable numeric value to an inclusive range."""
    return max(minimum, min(maximum, value))


def clamp01(value):
    """Limits an already-numeric score to the standard 0.0..1.0 range."""
    return clamp(value, 0.0, 1.0)


def clamp_float(value, minimum, maximum, default):
    """Coerces a persisted value to float, falling back when it is invalid."""
    try:
        return clamp(float(value), minimum, maximum)
    except (TypeError, ValueError):
        return default
