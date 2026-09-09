"""Legacy effect constructors shared during incremental ruleset migration."""


def op(kind, **kwargs):
    return {"kind": kind, **kwargs}


def option(label, effects=(), **kwargs):
    return {"label": label, "effects": list(effects), **kwargs}
