"""Stand-in ``gh`` executable that mimics real ``gh api`` pagination.

Responses come from the JSON file named by ``FAKE_GH_DATA`` (``{endpoint: [items]}``)
and are split into pages of ``FAKE_GH_PAGE_SIZE`` items. Like the real CLI,
``--jq`` is applied to *each page separately* (via the ``jq`` binary), so a
multi-page ``--paginate --jq '[...]'`` call prints several JSON arrays.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _api(args: list[str]) -> int:
    endpoint = args[0]
    paginate = "--paginate" in args
    jq_expr = args[args.index("--jq") + 1] if "--jq" in args else None

    with open(os.environ["FAKE_GH_DATA"], encoding="utf-8") as fh:
        data: dict[str, list[object]] = json.load(fh)
    if endpoint not in data:
        sys.stderr.write("gh: Not Found (HTTP 404)\n")
        return 1

    items = data[endpoint]
    size = int(os.environ.get("FAKE_GH_PAGE_SIZE", "30"))
    pages = [items[i : i + size] for i in range(0, len(items), size)] or [[]]
    if not paginate:
        pages = pages[:1]

    for page in pages:
        payload = json.dumps(page)
        if jq_expr is None:
            sys.stdout.write(payload)
            continue
        result = subprocess.run(
            ["jq", "-c", jq_expr], input=payload, capture_output=True, text=True, check=True
        )
        sys.stdout.write(result.stdout)
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--version"]:
        print("gh version 0.0.0-fake")
        return 0
    if argv[:3] == ["config", "get", "git_protocol"]:
        print("https")
        return 0
    if argv[:1] == ["api"]:
        return _api(argv[1:])
    sys.stderr.write(f"fake gh: unsupported command {argv!r}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
