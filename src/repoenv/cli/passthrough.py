"""Command class for options like ``renv run [ENV] [OPTIONS] -- COMMAND [ARGS...]``.

Click distributes positional arguments by count, not by where ``--`` appeared
on the command line: given one optional argument (``ENV``, nargs=1) and one
variadic argument (``COMMAND``, nargs=-1), ``renv run -- git status`` and
``renv run git status`` parse identically -- ``git`` always fills ``ENV``
first, leaving ``COMMAND=['status']``. That silently swallows the first
command word as an environment name whenever ``ENV`` is omitted.

``PassthroughCommand`` sidesteps the ambiguity by finding the first literal
``--`` itself, *before* Click's own parser ever sees it: everything left of it
goes through normal Click/Typer parsing (options plus the ``ENV`` argument),
and everything right of it is stashed untouched -- never matched against any
``Argument`` -- for the command function to read back via
:func:`get_passthrough_args`.
"""

from __future__ import annotations

from typing import Any

import typer
from typer.core import TyperCommand

_OBJ_KEY = "passthrough_args"


class PassthroughCommand(TyperCommand):
    """A :class:`TyperCommand` that splits its argv on the first ``--``."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        # ``ctx`` is typed ``Any`` (not ``typer.Context``) because the base
        # class' own parameter type is an internal alias that has moved
        # across typer versions (real ``click.Context`` vs. a vendored one);
        # matching it exactly here would be brittle. See didyoumean.py for
        # the same pattern.
        if "--" in args:
            index = args.index("--")
            head, tail = list(args[:index]), list(args[index + 1 :])
        else:
            head, tail = list(args), []
        ctx.ensure_object(dict)
        ctx.obj[_OBJ_KEY] = tail
        return super().parse_args(ctx, head)


def get_passthrough_args(ctx: typer.Context) -> list[str]:
    """Return the raw tokens captured after ``--`` for this invocation."""
    obj: dict[str, Any] = ctx.obj or {}
    return list(obj.get(_OBJ_KEY, []))
