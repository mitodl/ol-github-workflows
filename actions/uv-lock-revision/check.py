"""Assert that no uv.lock falls to an older format than the branch already has.

uv's lockfile carries two version keys with different promises. `version` is the
backwards-incompatible tier; `revision` is the backwards-compatible one -- an older uv
reads a lockfile with a higher revision, it just does not understand all the data
(https://github.com/astral-sh/uv/pull/11500). So `revision` is held to a floor and a
ratchet, and `version` is held exactly.

The lockfile is parsed as TOML rather than scanned line by line. A scanner has to decide
what `1_0`, `0x10` and a `version` key sitting under some `[[package]]` mean; a parser
already knows, and the answers are 10, 16, and "not the root table".

Run by actions/uv-lock-revision/action.yml. Reads EXPECTED_REVISION and EXPECTED_VERSION
from the environment, and exits non-zero when any lockfile is out of contract.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib

LOCKFILE_GLOB = "*uv.lock"


def annotate(level: str, message: str, path: str | None = None) -> None:
    """A GitHub workflow command. Keeps every message on one line, as the format needs."""
    where = f" file={path}" if path else ""
    print(f"::{level}{where}::{message.replace(chr(10), ' ')}")


def git(*args: str) -> subprocess.CompletedProcess:
    # Fixed arguments, and git is found on PATH because the runner decides where it lives.
    return subprocess.run(["git", *args], capture_output=True, check=False)  # noqa: S603, S607


def tracked_lockfiles() -> list[str]:
    """Every tracked path ending in uv.lock, so a workspace needs no configuration.

    The pathspec crosses `/` and matches a non-empty prefix, so a stray `notuv.lock` is
    checked too -- it errs toward checking more, not less.
    """
    out = git("ls-files", "-z", LOCKFILE_GLOB).stdout
    return [name for name in out.decode().split("\0") if name]


def base_commit() -> str | None:
    """What this change moves away from, or None when the checkout has no such commit.

    On a pull request the checked-out commit is the merge commit and its first parent is
    the branch being merged into; on a push it is the previous commit. Absent on a root
    commit or a single-commit checkout, in which case only the floor applies.
    """
    found = git("rev-parse", "--verify", "--quiet", "HEAD^1")
    return found.stdout.decode().strip() or None


class Unreadable(Exception):
    """The lockfile is there but does not say what it is."""


def lockfile_fields(data: bytes) -> tuple[int, int | None]:
    """The root table's `version` and `revision`, as integers.

    `revision` is None when the key is absent -- a lockfile old enough to predate it, or
    one written by something that is not uv.
    """
    try:
        parsed = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as err:
        raise Unreadable(f"not readable as TOML: {err}") from err
    version = parsed.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise Unreadable(f"root `version` is {version!r}, which is not a lockfile version")
    revision = parsed.get("revision")
    if revision is not None and (not isinstance(revision, int) or isinstance(revision, bool)):
        raise Unreadable(f"root `revision` is {revision!r}, which is not a revision number")
    return version, revision


def expected(name: str, noun: str) -> int:
    """An input read as a decimal integer, or the run stops before scanning anything.

    GitHub does not enforce `required:` on action inputs, so an omitted `with:` arrives
    here as an empty string -- an empty floor, which would admit any revision at all.
    """
    raw = os.environ.get(name, "")
    # ASCII as well as digits. `str.isdigit()` is true of "\u00b2" and "\u0663", and int()
    # then raises on the first and quietly returns 3 for the second -- a traceback and a
    # silently misread input, from a field that only ever holds a small decimal.
    if not (raw.isascii() and raw.isdigit()):
        annotate("error", f"{name.lower().replace('_', '-')} is {raw!r}, not a {noun}.")
        raise SystemExit(1)
    return int(raw)


def base_revision(base: str, lock: str) -> int | None:
    """The revision this same lockfile is on in the base commit, if it is there at all.

    A lockfile the change adds, or one it moved to a new path, has no copy there and is
    held to the floor alone.
    """
    shown = git("show", f"{base}:{lock}")
    if shown.returncode != 0:
        return None
    try:
        return lockfile_fields(shown.stdout)[1]
    except Unreadable:
        return None


def main() -> int:
    floor = expected("EXPECTED_REVISION", "revision number")
    want_version = expected("EXPECTED_VERSION", "lockfile version number")
    base = base_commit()

    status = 0
    locks = tracked_lockfiles()
    compared = 0

    for lock in locks:
        # isfile() follows the symlink and is false for a device or a directory, as the
        # shell's `[ -f ]` was: reading a lockfile symlinked to /dev/zero never reaches EOF.
        if not os.path.isfile(lock):
            missing = "not a regular file" if os.path.lexists(lock) else "missing from the checkout"
            annotate("error", f"tracked by git but {missing}", lock)
            status = 1
            continue

        try:
            with open(lock, "rb") as handle:
                raw = handle.read()
        except OSError as err:
            annotate("error", f"could not be read: {err.strerror}", lock)
            status = 1
            continue

        try:
            version, revision = lockfile_fields(raw)
        except Unreadable as err:
            annotate("error", str(err), lock)
            status = 1
            continue

        if version != want_version:
            annotate(
                "error",
                f"lockfile version is {version}, expected {want_version}. The version is "
                "uv's backwards-incompatible tier, so moving it is a migration: make it "
                "deliberately and set expected-version in the same pull request.",
                lock,
            )
            status = 1

        if revision is None:
            annotate(
                "error",
                f"lockfile revision is absent, expected at least {floor}.",
                lock,
            )
            status = 1
            continue

        if revision < floor:
            annotate(
                "error",
                f"lockfile revision is {revision}, below the floor of {floor}. A uv that "
                "re-resolves (uv add, uv lock --upgrade) rewrites this; re-lock with a uv "
                f"new enough to write {floor}.",
                lock,
            )
            status = 1
            continue

        was = base_revision(base, lock) if base else None
        if was is not None:
            compared += 1
            if revision < was:
                annotate(
                    "error",
                    f"lockfile revision fell from {was} to {revision}. An older uv "
                    f"re-resolved this and wrote it back without the fields revision {was} "
                    "carried; re-lock with a current uv.",
                    lock,
                )
                status = 1
                continue

        if revision > floor:
            annotate(
                "notice",
                f"lockfile revision is {revision}, above the floor of {floor}. Raising "
                f"expected-revision to {revision} would hold the gain.",
                lock,
            )

    if not locks:
        annotate("error", "no uv.lock found, so this action does not belong in this repository")
        status = 1

    # Name what the ratchet actually covered. A run where it compared nothing, or only
    # some of the lockfiles, must not read like one where it compared them all.
    summary = f"checked {len(locks)} lockfile(s) against floor {floor}"
    if base is None:
        summary += "; no parent commit in this checkout, so the ratchet did not run"
    else:
        summary += f"; {compared} of them also against {base[:7]}"
        if compared < len(locks):
            summary += f", the other {len(locks) - compared} against the floor alone"
    print(summary)
    return status


if __name__ == "__main__":
    sys.exit(main())
