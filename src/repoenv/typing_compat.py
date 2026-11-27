"""Runtime typing compatibility shims.

Python 3.14 adjusted the private ``typing._eval_type`` signature. Some third-party
libraries (notably Pydantic) may call it with kwargs that no longer exist.
This module provides a small, targeted shim so repo-env keeps working on 3.14
until upstream libraries catch up in the dependency set available to this repo.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeGuard

_MARKER = "_repoenv_eval_type_shim"  # set on our wrapper so repeated calls do not wrap it again


def patch_typing_eval_type() -> None:
    """Patch ``typing._eval_type`` to accept deprecated kwargs when missing.

    Safe to call multiple times.
    """
    import typing

    original = getattr(typing, "_eval_type", None)
    if not _needs_shim(original):
        return

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        # Transparent pass-through: only drop prefer_fwd_module, which Python 3.14
        # removed from typing._eval_type; every other argument is forwarded as given.
        kwargs.pop("prefer_fwd_module", None)
        return original(*args, **kwargs)

    setattr(_wrapped, _MARKER, True)
    setattr(typing, "_eval_type", _wrapped)


def _needs_shim(eval_type: object) -> TypeGuard[Callable[..., Any]]:
    """True when ``eval_type`` is callable, not yet wrapped and lacks ``prefer_fwd_module``."""
    import inspect

    if not callable(eval_type) or getattr(eval_type, _MARKER, False):
        return False
    try:
        params = inspect.signature(eval_type).parameters
    except (TypeError, ValueError):
        return False
    return "prefer_fwd_module" not in params
