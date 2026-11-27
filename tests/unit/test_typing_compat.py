from __future__ import annotations

import typing

import pytest

from repoenv import typing_compat


def test_patch_is_idempotent_and_drops_prefer_fwd_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_eval_type(value: object, globalns: object, localns: object) -> object:
        calls.append(((value, globalns, localns), {}))
        return value

    monkeypatch.setattr(typing, "_eval_type", fake_eval_type, raising=False)
    typing_compat.patch_typing_eval_type()
    wrapper = typing._eval_type  # type: ignore[attr-defined]
    typing_compat.patch_typing_eval_type()

    assert typing._eval_type is wrapper  # type: ignore[attr-defined]
    assert wrapper(int, None, None, prefer_fwd_module=True) is int
    assert calls == [((int, None, None), {})]
