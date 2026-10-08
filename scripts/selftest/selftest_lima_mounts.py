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

# D-205: the VM mounts no host project writable. Projects reach it only by
# copy-in (scripts/vm-sync start) and come back only as checked commits
# (vm-sync land). The builder checkout is mounted READ-ONLY so swbp and its
# helpers can run inside the VM.
EXPECTED_WRITABLE: set[str] = set()
EXPECTED_READ_ONLY = {"~/dev/sw-dev-blueprint"}


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


def test_no_host_project_is_writable_from_the_vm() -> None:
    """D-205: nothing is mounted writable; only the builder, read-only."""
    mounts = _mounts()
    writable = {m["location"] for m in mounts if m["writable"]}
    read_only = {m["location"] for m in mounts if m["writable"] is False}
    assert writable == EXPECTED_WRITABLE, f"writable mounts: {sorted(writable)}"
    assert read_only == EXPECTED_READ_ONLY, f"read-only mounts: {sorted(read_only)}"


# --- Security plan item 10b: the VM is built from pinned, verified inputs ---

def _config_text() -> str:
    return LIMA_CONFIG.read_text()


def test_base_images_are_dated_and_digest_pinned() -> None:
    text = _config_text()
    locations = re.findall(r'location:\s*"(https://cloud-images[^"]+)"', text)
    assert locations, "no cloud image locations found"
    for loc in locations:
        assert "/release/" not in loc, f"floating 'release/' image: {loc}"
        assert re.search(r"/release-\d{8}/", loc), f"image is not a dated release: {loc}"
    assert len(re.findall(r'digest:\s*"sha256:[0-9a-f]{64}"', text)) == len(locations), \
        "every image needs a sha256 digest"


def test_no_script_is_piped_into_a_shell() -> None:
    text = _config_text()
    assert not re.search(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b", text), "curl | bash in provisioning"


def test_downloads_are_version_pinned_and_verified() -> None:
    text = _config_text()
    assert "releases/latest" not in text, "a floating 'latest' release is installed"
    assert re.search(r"@anthropic-ai/claude-code@\d+\.\d+\.\d+", text), "Claude Code version not pinned"
    assert "sha256sum -c" in text, "downloaded packages are not checksum-verified"
    assert re.search(r'NODESOURCE_FPR="[0-9A-F]{40}"', text), "NodeSource key fingerprint not pinned"
