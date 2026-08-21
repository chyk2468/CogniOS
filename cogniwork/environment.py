"""Session environment context — injected into the system prompt at engine build.

Saves the agent 3-4 discovery tool calls every session (pwd, uname, git status, git log)
by telling it up front where it is and what state the workspace is in. The git snapshot is
point-in-time; the prompt labels it as such so the agent re-checks before relying on it.
"""

from __future__ import annotations

import platform as _platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _git(workspace: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _git_snapshot(workspace: Path) -> list[str]:
    if _git(workspace, "rev-parse", "--is-inside-work-tree") != "true":
        return ["Git: not a git repository"]

    lines = []
    branch = _git(workspace, "rev-parse", "--abbrev-ref", "HEAD") or "(unknown)"
    lines.append(f"Git branch: {branch}")

    status = _git(workspace, "status", "--porcelain")
    if status is not None:
        changed = status.splitlines()
        if not changed:
            lines.append("Git status: clean")
        else:
            shown = "\n".join(changed[:20])
            more = f"\n… and {len(changed) - 20} more" if len(changed) > 20 else ""
            lines.append(f"Git status ({len(changed)} changed):\n{shown}{more}")

    log = _git(workspace, "log", "-n5", "--pretty=format:%h %s")
    if log:
        lines.append(f"Recent commits:\n{log}")
    return lines


def environment_context(workspace: str | Path | None = None) -> str:
    """A system-prompt block describing the session's environment, temporal context, and git state."""
    mac = _platform.mac_ver()[0]
    os_name = f"macOS {mac}" if mac else f"{_platform.system()} {_platform.release()}"

    now = datetime.now().astimezone()
    day_name = now.strftime("%A")
    formatted_date = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M:%S %p %Z").strip()
    iso_date = now.strftime("%Y-%m-%d")

    lines = [
        f"Platform: {sys.platform} ({os_name})",
        f"Today's date: {iso_date} ({day_name})",
        f"Current date & time: {formatted_date}, {time_str}",
        f"Day of the week: {day_name}",
    ]

    if workspace is not None:
        ws = Path(workspace).expanduser().resolve()
        lines.insert(0, f"Workspace: {ws}")
        lines.extend(_git_snapshot(ws))
    else:
        lines.insert(0, "Workspace: (no workspace bound)")

    body = "\n".join(lines)
    return (
        "Environment (snapshot from session start — verify before relying on git "
        f"state):\n<environment>\n{body}\n</environment>\n"
        "Folder scope: work inside the workspace and any folders the user has granted. Do not "
        "read or list other locations (home directory sweeps, ~/Desktop, ~/Downloads, photo "
        "libraries, etc.) — not even via shell commands like find/ls/grep. On macOS every such "
        "touch fires an OS permission prompt the user can't connect to any action they took. "
        "If a task needs files elsewhere, ask first with request_directory."
    )
