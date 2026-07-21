"""Unit tests for new selection features: ** globbing and ~ / absolute-path normalisation."""

from __future__ import annotations

from repoenv.domain.selection import resolve_selection

# ---------------------------------------------------------------------------
# ** globbing
# ---------------------------------------------------------------------------


def test_double_star_matches_multi_level_path() -> None:
    result = resolve_selection(
        ["org/demo-repo", "org/sub/demo-foo", "unrelated"],
        include=["**/demo-*"],
    )
    assert result == ["org/demo-repo", "org/sub/demo-foo"]


def test_double_star_matches_top_level() -> None:
    """A ``**`` pattern should also match names without any path separator."""
    result = resolve_selection(
        ["demo-repo", "other"],
        include=["**/demo-*"],
    )
    assert result == ["demo-repo"]


def test_double_star_in_exclude() -> None:
    result = resolve_selection(
        ["org/demo-repo", "org/keep-me"],
        exclude=["**/demo-*"],
    )
    assert result == ["org/keep-me"]


def test_single_star_does_not_match_path_separator() -> None:
    """``*`` must not cross ``/``."""
    result = resolve_selection(
        ["org/demo-repo", "demo-top"],
        include=["demo-*"],
    )
    assert result == ["demo-top"]


# ---------------------------------------------------------------------------
# Comma-separated patterns (pre-existing behaviour regression)
# ---------------------------------------------------------------------------


def test_csv_include_pattern_is_split() -> None:
    result = resolve_selection(["alpha", "beta", "gamma"], include=["alpha,beta"])
    assert result == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# resolve_selection – general contract
# ---------------------------------------------------------------------------


def test_no_include_selects_all() -> None:
    assert resolve_selection(["a", "b"]) == ["a", "b"]


def test_exclude_takes_precedence_over_include() -> None:
    result = resolve_selection(["alpha", "beta"], include=["*"], exclude=["beta"])
    assert result == ["alpha"]
