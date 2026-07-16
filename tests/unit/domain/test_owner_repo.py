from __future__ import annotations

import pytest

from repoenv.domain.owner_repo import (
    expand_owner_repo_patterns,
    has_wildcard,
    match_owner_repo,
    validate_owner_repo_pattern,
)
from repoenv.errors import UsageError


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("myself/test-*", ("myself", "test-*")),
        ("owner/repo2", ("owner", "repo2")),
        ("prefix-*/*", ("prefix-*", "*")),
        ("**", ("*", "*")),
    ],
)
def test_validate_owner_repo_pattern_valid(pattern: str, expected: tuple[str, str]) -> None:
    assert validate_owner_repo_pattern(pattern) == expected


@pytest.mark.parametrize(
    "pattern",
    [
        "no-slash-here",
        "*",
        "owner/repo/extra",
        "/repo",
        "owner/",
        "",
    ],
)
def test_validate_owner_repo_pattern_rejects_invalid(pattern: str) -> None:
    with pytest.raises(UsageError):
        validate_owner_repo_pattern(pattern)


def test_expand_owner_repo_patterns_supports_csv_and_repeatable() -> None:
    result = expand_owner_repo_patterns(["owner/repo1,owner/repo2", "prefix-*/*"])
    assert result == [("owner", "repo1"), ("owner", "repo2"), ("prefix-*", "*")]


def test_has_wildcard() -> None:
    assert has_wildcard("prefix-*") is True
    assert has_wildcard("owner?") is True
    assert has_wildcard("[abc]") is True
    assert has_wildcard("literal-owner") is False


def test_match_owner_repo() -> None:
    patterns = expand_owner_repo_patterns(["myself/test-*", "owner/repo2"])
    assert match_owner_repo("myself", "test-alpha", patterns) is True
    assert match_owner_repo("owner", "repo2", patterns) is True
    assert match_owner_repo("owner", "repo1", patterns) is False
    assert match_owner_repo("someone-else", "test-alpha", patterns) is False


def test_match_owner_repo_wildcard_owner_does_not_leak_across_slash() -> None:
    patterns = expand_owner_repo_patterns(["prefix-*/*"])
    assert match_owner_repo("prefix-a", "anything", patterns) is True
    assert match_owner_repo("other", "anything", patterns) is False
