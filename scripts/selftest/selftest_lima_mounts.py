"""D-196 Lima mount narrowing (lima/dev-vm.yaml).

The VM config mounted ~/dev wholesale writable — every project under ~/dev
(some hold .env secrets) was reachable from skip-permissions conductors.
D-196 narrows the writable surface to the four working projects; the
stronger copy-in/copy-out fix is scheduled separately. These tests parse
the YAML text (stdlib-only: the CI selftest job installs pytest/ruff but
no YAML library) and pin the narrowed surface: no ~/dev or ~/ mount, and
writable: true only for the four listed paths.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIMA_CONFIG = REPO / "lima" / "dev-vm.yaml"

# The only paths the VM may mount writable (D-196).
EXPECTED_WRITABLE = {
    "~/dev/sw-dev-blueprint",
    "~/dev/vortex",
    "~/dev/testchat",
    "~/dev/rich-adoption",
}


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_mounts(text: str) -> list[dict]:
    """Parse the top-level `mounts:` block of the Lima config.

    Line-oriented on purpose: the block is a flat list of {location,
    writable} pairs, which is all this gate needs, and the CI selftest
    environment has no YAML library.
    """
    mounts: list[dict] = []
    current: dict | None = None
    in_mounts = False
    for raw in text.splitlines():
        if not in_mounts:
            if re.match(r"^mounts:\s*(#.*)?$", raw):
                in_mounts = True
            continue
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace() and not raw.lstrip().startswith("-"):
            break  # the next top-level key ends the block
        item = re.match(r"^\s*-\s*location:\s*(\S+?)\s*(?:#.*)?$", raw)
        if item:
            current = {"location": _unquote(item.group(1)), "writable": None}
            mounts.append(current)
            continue
        flag = re.match(r"^\s*writable:\s*(\S+?)\s*(?:#.*)?$", raw)
        if flag:
            if current is None:
                raise ValueError("writable: without a preceding location:")
            current["writable"] = flag.group(1).lower() == "true"
    return mounts


def _mounts() -> list[dict]:
    assert LIMA_CONFIG.is_file(), f"missing Lima config: {LIMA_CONFIG}"
    return parse_mounts(LIMA_CONFIG.read_text())


def test_mounts_block_present_and_explicit() -> None:
    """Fail closed: the block parses and every entry declares its writability."""
    mounts = _mounts()
    assert mounts, "no mounts parsed — the mounts: block is missing or malformed"
    for mount in mounts:
        assert mount["location"], f"mount with empty location: {mount}"
        assert mount["writable"] is not None, (
            f"mount without an explicit writable flag (Lima's default is "
            f"ambiguous): {mount}"
        )


def test_no_whole_dev_or_home_mount() -> None:
    """~/dev and ~/ are never mounted — that is the pre-D-196 over-reach."""
    locations = {m["location"] for m in _mounts()}
    for whole in ("~/dev", "~/dev/", "~", "~/"):
        assert whole not in locations, f"whole {whole} is mounted"


def test_writable_true_only_for_the_four_projects() -> None:
    """writable: true is exactly the four working projects — nothing else."""
    writable = {m["location"] for m in _mounts() if m["writable"]}
    assert writable == EXPECTED_WRITABLE, (
        f"writable mounts {sorted(writable)} != expected {sorted(EXPECTED_WRITABLE)}"
    )
