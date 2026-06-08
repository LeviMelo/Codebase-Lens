from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd()
SNAPSHOT = ROOT / "src" / "codebase_lens" / "reports" / "snapshot.py"


def main() -> int:
    text = SNAPSHOT.read_text(encoding="utf-8")

    if "import json\n" not in text:
        marker = "from __future__ import annotations\n\n"
        if marker not in text:
            raise RuntimeError("Could not find future-import marker in reports/snapshot.py.")
        text = text.replace(marker, marker + "import json\n", 1)

    if "from codebase_lens.git.discover import collect_git_info\n" not in text:
        marker = "from codebase_lens.git.diff import collect_changed_files\n"
        if marker not in text:
            raise RuntimeError("Could not find git.diff import marker in reports/snapshot.py.")
        text = text.replace(
            marker,
            marker + "from codebase_lens.git.discover import collect_git_info\n",
            1,
        )

    SNAPSHOT.write_text(text, encoding="utf-8", newline="\n")

    ast.parse(SNAPSHOT.read_text(encoding="utf-8"))

    print("Repair applied: reports/snapshot.py now imports json and collect_git_info.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())