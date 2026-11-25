"""Runtime typing compatibility shims.

Python 3.14 adjusted the private ``typing._eval_type`` signature. Some third-party
libraries (notably Pydantic) may call it with kwargs that no longer exist.
This module provides a small, targeted shim so repo-env keeps working on 3.14
until upstream libraries catch up in the dependency set available to this repo.
"""

from __future__ import annotations

from typing import Any


def patch_typing_eval_type() -> None:
    """Patch ``typing._eval_type`` to accept deprecated kwargs when missing.

    Safe to call multiple times.
    """
    import inspect
    import typing

    eval_type = getattr(typing, "_eval_type", None)
    if eval_type is None or not callable(eval_type):
        return

    try:
        params = inspect.signature(eval_type).parameters
    except (TypeError, ValueError):
        return

    if "prefer_fwd_module" in params:
        return

    original = eval_type

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        # Transparent pass-through: only drop prefer_fwd_module, which Python 3.14
        # removed from typing._eval_type; every other argument is forwarded as given.
        kwargs.pop("prefer_fwd_module", None)
        return original(*args, **kwargs)

    setattr(typing, "_eval_type", _wrapped)
