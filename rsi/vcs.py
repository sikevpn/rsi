"""Version-control snapshots used by the quality ratchet.

Report §4: "每次自改前 git commit 快照；回归不达标即 ``git revert``".  The loop takes a
:class:`VCS` so tests can run against a real git repository or against a no-op.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = ["VCS", "NoopVCS", "GitVCS"]


@runtime_checkable
class VCS(Protocol):
    def snapshot(self, message: str) -> bool:  # pragma: no cover - protocol
        ...

    def revert_last(self) -> bool:  # pragma: no cover - protocol
        ...

    def changed_paths(self) -> list[str]:  # pragma: no cover - protocol
        ...


@dataclass
class NoopVCS:
    """Records intent without touching git (used when the target is not a repo)."""

    snapshots: list[str] | None = None
    reverts: int = 0

    def __post_init__(self) -> None:
        if self.snapshots is None:
            self.snapshots = []

    def snapshot(self, message: str) -> bool:
        self.snapshots.append(message)  # type: ignore[union-attr]
        return True

    def revert_last(self) -> bool:
        self.reverts += 1
        return True

    def changed_paths(self) -> list[str]:
        return []


class GitVCS:
    """Thin git wrapper.  Never raises: failures are reported as booleans."""

    def __init__(self, cwd: str | Path) -> None:
        self.cwd = Path(cwd)

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=str(self.cwd),
            capture_output=True,
            text=True,
            check=False,
        )

    def is_repo(self) -> bool:
        """True only when ``cwd`` is itself the repository root.

        Guards against snapshotting into some unrelated parent repository when the
        target project happens to live inside one.
        """
        proc = self._git("rev-parse", "--show-toplevel")
        if proc.returncode != 0:
            return False
        try:
            return Path(proc.stdout.strip()).resolve() == self.cwd.resolve()
        except OSError:
            return False

    def snapshot(self, message: str) -> bool:
        if not self.is_repo():
            return False
        self._git("add", "-A")
        proc = self._git(
            "-c",
            "user.name=rsi-loop",
            "-c",
            "user.email=rsi-loop@localhost",
            "commit",
            "-m",
            message,
            "--allow-empty",
        )
        return proc.returncode == 0

    def revert_last(self) -> bool:
        if not self.is_repo():
            return False
        proc = self._git("reset", "--hard", "HEAD~1")
        return proc.returncode == 0

    def changed_paths(self) -> list[str]:
        if not self.is_repo():
            return []
        proc = self._git("status", "--porcelain")
        if proc.returncode != 0:
            return []
        out: list[str] = []
        for line in proc.stdout.splitlines():
            if len(line) > 3:
                out.append(line[3:].strip().strip('"'))
        return out
