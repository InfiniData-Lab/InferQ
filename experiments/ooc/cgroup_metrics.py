"""Read cgroup accounting for Docker containers, with legacy scope helpers.

Works on Linux with cgroup v2 (unified hierarchy). Returns 0 / None on platforms
without /sys/fs/cgroup (e.g. macOS dev) so the orchestrator can still run in dry
mode off-box.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_SUDO_WARN_EMITTED = False

# On hybrid cgroup systems the v2 unified hierarchy is mounted at
# /sys/fs/cgroup/unified, not at /sys/fs/cgroup (which is a plain tmpfs).
# Detect at import time so all helpers use the right root.
def _detect_cgroup_v2_root() -> Path:
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[2] == "cgroup2":
                    return Path(parts[1])
    except Exception:
        pass
    return Path("/sys/fs/cgroup")

CGROUP_ROOT = _detect_cgroup_v2_root()
CGROUP_V1_MEM_ROOT = Path("/sys/fs/cgroup/memory")


@dataclass
class CgroupSnapshot:
    memory_peak_bytes: int
    memory_swap_peak_bytes: int
    io_read_bytes: int
    io_write_bytes: int
    cgroup_path: str


def _read_priv(path: Path) -> str:
    """Read a cgroup file, escalating to `sudo -n cat` on PermissionError.

    cgroup v1 paths under /sys/fs/cgroup/memory/docker/<id>/ are root-only on
    most distros. Without escalation the read returns "" and downstream
    metrics silently report 0, which previously let a sibling container's
    self-report win the merge for postgres rows.
    """
    global _SUDO_WARN_EMITTED
    try:
        return path.read_text()
    except (FileNotFoundError, IsADirectoryError):
        return ""
    except PermissionError:
        try:
            r = subprocess.run(
                ["sudo", "-n", "cat", str(path)],
                capture_output=True, text=True, check=False,
            )
        except FileNotFoundError:
            return ""
        if r.returncode == 0:
            return r.stdout
        if not _SUDO_WARN_EMITTED:
            sys.stderr.write(
                f"[cgroup_metrics] cannot read {path} as user; sudo -n cat failed "
                f"(rc={r.returncode}: {r.stderr.strip()[:120]}). Postgres cgroup "
                f"metrics will be null. Add a NOPASSWD sudoers entry for "
                f"`cat /sys/fs/cgroup/memory/docker/*` to fix.\n"
            )
            _SUDO_WARN_EMITTED = True
        return ""


def _read_int(path: Path) -> int:
    text = _read_priv(path).strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def _parse_io_stat(path: Path) -> tuple[int, int]:
    """Sum rbytes/wbytes across all devices in io.stat."""
    read_b = write_b = 0
    content = _read_priv(path)
    if not content:
        return 0, 0
    for line in content.splitlines():
        parts = line.split()
        for field in parts[1:]:
            if "=" not in field:
                continue
            k, v = field.split("=", 1)
            if k == "rbytes":
                read_b += int(v)
            elif k == "wbytes":
                write_b += int(v)
    return read_b, write_b


def _try_v2_swap_peak_for_v1_path(v1_path: Path) -> int | None:
    """If a v2 unified sibling exists for the same docker container, return
    its memory.swap.peak. Returns None on pure-v1 hosts or when the sibling
    can't be located.
    """
    name = v1_path.name
    if not name:
        return None
    # _detect_cgroup_v2_root() already picked the unified mount when present.
    # On hybrid hosts that's typically /sys/fs/cgroup/unified, distinct from
    # the v1 memory root used by the caller.
    v2_roots: list[Path] = []
    if CGROUP_ROOT != CGROUP_V1_MEM_ROOT and CGROUP_ROOT.exists():
        v2_roots.append(CGROUP_ROOT)
    unified = Path("/sys/fs/cgroup/unified")
    if unified.exists() and unified not in v2_roots:
        v2_roots.append(unified)
    for root in v2_roots:
        for layout in (f"docker/{name}",
                       f"system.slice/docker-{name}.scope",
                       f"system.slice/docker.service/docker/{name}"):
            cand = root / layout / "memory.swap.peak"
            if cand.exists():
                txt = _read_priv(cand).strip()
                if txt:
                    try:
                        return int(txt)
                    except ValueError:
                        return None
    return None


def read_cgroup(cgroup_path: Path) -> CgroupSnapshot:
    """Read peak memory and cumulative I/O counters from a cgroup path.

    Handles both cgroup v1 memory paths (/sys/fs/cgroup/memory/...) and
    cgroup v2 unified paths. On v1, memory.max_usage_in_bytes gives true peak.
    On v2, memory.peak (kernel ≥5.19) or memory.current is used.
    """
    is_v1_mem = str(cgroup_path).startswith(str(CGROUP_V1_MEM_ROOT))
    if is_v1_mem:
        mem_peak = _read_int(cgroup_path / "memory.max_usage_in_bytes")
        memsw = _read_int(cgroup_path / "memory.memsw.max_usage_in_bytes")
        # Prefer v2 swap.peak from a unified sibling when present (hybrid hosts);
        # otherwise fall back to memsw - mem, which is a *lower bound* on swap
        # because the two component peaks may not coincide in time.
        v2_swap = _try_v2_swap_peak_for_v1_path(cgroup_path)
        swap_peak = v2_swap if v2_swap is not None else max(0, memsw - mem_peak)
        return CgroupSnapshot(
            memory_peak_bytes=mem_peak,
            memory_swap_peak_bytes=swap_peak,
            io_read_bytes=0,
            io_write_bytes=0,
            cgroup_path=str(cgroup_path),
        )

    mem_peak = _read_int(cgroup_path / "memory.peak")
    if mem_peak == 0:
        mem_peak = _read_int(cgroup_path / "memory.current")
    swap_peak = _read_int(cgroup_path / "memory.swap.peak")
    return CgroupSnapshot(
        memory_peak_bytes=mem_peak,
        memory_swap_peak_bytes=swap_peak,
        io_read_bytes=_parse_io_stat(cgroup_path / "io.stat")[0],
        io_write_bytes=_parse_io_stat(cgroup_path / "io.stat")[1],
        cgroup_path=str(cgroup_path),
    )


def find_systemd_scope_cgroup(unit_name: str) -> Path | None:
    """Find cgroup path for a legacy systemd-run --user --scope unit.

    The current orchestrator uses Docker containers. This helper remains for
    older result-inspection scripts. Prefer cgroup v2 unified; cgroup v1 memory
    often points to a parent slice on hybrid systems and aggregates unrelated
    activity.
    """
    uid = os.getuid()
    # v2 first; v1 only as a desperate fallback.
    for root in (CGROUP_ROOT, CGROUP_V1_MEM_ROOT):
        if not root.exists():
            continue
        candidates = [
            root / f"user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit_name}",
            root / f"user.slice/user-{uid}.slice/user@{uid}.service/{unit_name}",
            root / f"system.slice/{unit_name}",
        ]
        for c in candidates:
            if c.exists():
                return c
        # Exact-name match anywhere under the root. The unit name is a UUID
        # suffix so this won't accidentally match a parent.
        matches = list(root.rglob(unit_name))
        if matches:
            return matches[0]
    return None


def find_docker_cgroup(container_id: str) -> Path | None:
    """Find cgroup path for a Docker container by id or name.

    Tries cgroup v1 (memory) and v2 unified, plus both Docker drivers
    (cgroupfs + systemd) and hybrid layouts. Returns the first directory
    that contains a memory accounting file so the caller can read counters
    immediately without further dispatch.
    """
    try:
        full_id = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.Id}}", container_id],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        full_id = container_id

    # Roots in order of preference: v1 memory (true peak via
    # max_usage_in_bytes), then v2 unified, then the legacy systemd named
    # hierarchy at CGROUP_ROOT.
    roots: list[Path] = []
    if CGROUP_V1_MEM_ROOT.exists():
        roots.append(CGROUP_V1_MEM_ROOT)
    unified = Path("/sys/fs/cgroup/unified")
    if unified.exists():
        roots.append(unified)
    if CGROUP_ROOT.exists() and CGROUP_ROOT not in roots:
        roots.append(CGROUP_ROOT)

    layouts = [
        f"docker/{full_id}",
        f"system.slice/docker-{full_id}.scope",
        f"system.slice/docker.service/docker/{full_id}",
    ]
    for root in roots:
        for layout in layouts:
            c = root / layout
            if c.exists():
                return c

    # Fallback: walk roots looking for a directory whose name contains the id.
    pattern = re.compile(re.escape(full_id))
    for root in roots:
        for parent, dirs, _ in os.walk(root):
            for d in dirs:
                if pattern.search(d):
                    return Path(parent) / d
    return None


def drop_page_cache(use_sudo: bool = True) -> bool:
    """Flush OS page cache so spill-from-disk measurements are cold.

    Requires `echo 3 > /proc/sys/vm/drop_caches` which is root-only. With
    use_sudo, expects a NOPASSWD sudoers entry for `tee /proc/sys/vm/drop_caches`.
    Returns True on success, False otherwise.
    """
    try:
        subprocess.check_call(["sync"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    cmd_tee = ["tee", "/proc/sys/vm/drop_caches"]
    if use_sudo:
        cmd_tee = ["sudo", "-n"] + cmd_tee
    try:
        p = subprocess.run(cmd_tee, input=b"3\n", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return p.returncode == 0
    except FileNotFoundError:
        return False
