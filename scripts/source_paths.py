"""Source-lane paths and writes shared by the plan gate and coder appliers.

The checkout and lane configuration belong to the trusted host. Walk relative
to directory descriptors without following symlinks; replace files atomically
so even a hard-linked destination cannot cause a write to another file.
"""

import os
import secrets
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator


def build_lane() -> str:
    lane = "src"
    config = Path(".gate-paths")
    if config.exists():
        for line in config.read_text().splitlines():
            if line.startswith("build="):
                lane = line.split("=", 1)[1].strip().removeprefix("./").rstrip("/")
    return lane


def components(path: str) -> list[str]:
    if (not isinstance(path, str) or not path or "\\" in path
            or any(c in path for c in ("\0", "\n", "\r"))):
        raise ValueError(f"unsafe source path: {path!r}")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"source path must be canonical and relative: {path!r}")
    return parts


def source_parts(path: str, lane: str | None = None) -> list[str]:
    parts = components(path)
    base = components((lane if lane is not None else build_lane()).rstrip("/"))
    if len(parts) <= len(base) or parts[:len(base)] != base:
        raise ValueError(f"file must be under the build lane {'/'.join(base) + '/'!r}: {path!r}")
    return parts


@contextmanager
def parent_fd(path: str, *, create: bool = False,
              lane: str | None = None) -> Iterator[tuple[int, str]]:
    parts = source_parts(path, lane)
    fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, parts[-1]
    finally:
        os.close(fd)


def regular_target(fd: int, name: str) -> os.stat_result | None:
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"source destination must be a regular file, not a symlink/device: {name}")
    return info


def validate_source_path(path: str, lane: str | None = None) -> None:
    # Check all EXISTING ancestors. Missing directories are legitimate for a
    # create task, but lexical containment is established before this walk.
    source_parts(path, lane)
    try:
        with parent_fd(path, lane=lane) as (fd, name):
            regular_target(fd, name)
    except FileNotFoundError:
        pass


def read_source(path: str) -> str:
    with parent_fd(path) as (fd, name):
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(source, encoding="utf-8") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("source is not a regular file")
            return stream.read()


def write_source(path: str, content: str) -> None:
    validate_source_path(path)
    with parent_fd(path, create=True) as (fd, name):
        previous = regular_target(fd, name)
        temporary = ".swbp-write-" + secrets.token_hex(12)
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      0o666, dir_fd=fd)
        try:
            with os.fdopen(out, "w", encoding="utf-8") as stream:
                stream.write(content)
                if previous is not None:
                    os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode))
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("usage: source_paths.py <source-path>")
        validate_source_path(sys.argv[1])
    except (OSError, ValueError) as exc:
        sys.exit(f"unsafe source destination: {exc}")
