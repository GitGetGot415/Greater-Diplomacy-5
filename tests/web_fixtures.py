"""A stand-in for pygbag's platform.window that garbles text the way pygbag does."""

import json


def garble(text):
    """Reproduce pygbag 0.9.3: each UTF-8 byte of non-ASCII text arrives as one Latin-1 character."""
    return text.encode("utf-8").decode("latin-1")


class GarblingWindow:
    """Forward platform.window calls to a QuickJS context, garbling every string."""

    def __init__(self, context):
        object.__setattr__(self, "_context", context)

    def _global(self, name):
        return "window[" + json.dumps(name) + "]"

    def eval(self, source):
        return self._context.eval(garble(source))

    def __getattr__(self, name):
        kind = self._context.eval("typeof " + self._global(name))
        if kind == "undefined":
            raise AttributeError(name)
        if kind != "function":
            return self._context.eval(self._global(name))

        def call(*args):
            literals = ", ".join(
                json.dumps(garble(arg) if isinstance(arg, str) else arg) for arg in args)
            return self._context.eval(f"{self._global(name)}({literals})")
        return call

    def __setattr__(self, name, value):
        self._context.eval(f"{self._global(name)} = {json.dumps(value)}")
