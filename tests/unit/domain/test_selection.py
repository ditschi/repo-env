from __future__ import annotations

from repoenv.domain.selection import SetOp, resolve_selection, set_combine


def test_resolve_selection_include_exclude_ordered() -> None:
    candidates = ["alpha", "beta", "gamma", "beta"]
    selected = resolve_selection(candidates, include=["*a*"], exclude=["g*"])
    assert selected == ["alpha", "beta"]


def test_set_combine_union_intersect_difference() -> None:
    left = ["a", "b", "c"]
    right = ["b", "c", "d"]
    assert set_combine(left, right, SetOp.UNION) == ["a", "b", "c", "d"]
    assert set_combine(left, right, SetOp.INTERSECT) == ["b", "c"]
    assert set_combine(left, right, SetOp.DIFFERENCE) == ["a"]
