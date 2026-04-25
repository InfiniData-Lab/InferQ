"""Read cgroup v2 accounting for a systemd-run scope or Docker container.

Works on Linux with cgroup v2 (unified hierarchy). Returns 0 / None on platforms
without /sys/fs/cgroup (e.g. macOS dev) so the orchestrator can still run in dry
mode off-box.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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


def _read_int(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError, PermissionError):
        return 0


def _parse_io_stat(path: Path) -> tuple[int, int]:
    """Sum rbytes/wbytes across all devices in io.stat."""
    read_b = write_b = 0
    try:
        content = path.read_text()
    except (FileNotFoundError, PermissionError):
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


def read_cgroup(cgroup_path: Path) -> CgroupSnapshot:
    """Read peak memory and cumulative I/O counters from a cgroup path.

    Handles both cgroup v1 memory paths (/sys/fs/cgroup/memory/...) and
    cgroup v2 unified paths. On v1, memory.max_usage_in_bytes gives true peak.
    On v2, memory.peak (kernel ≥5.19) or memory.current is used.
    """
    is_v1_mem = str(cgroup_path).startswith(str(CGROUP_V1_MEM_ROOT))
    if is_v1_mem:
        mem_peak = _read_int(cgroup_path / "memory.max_usage_in_bytes")
        swap_peak = _read_int(cgroup_path / "memory.memsw.max_usage_in_bytes")
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


def find_systemd_scope_cgroup(unit_name: str) -> Optional[Path]:
    """Find cgroup path for a systemd-run --user --scope unit.

    Prefers cgroup v2 unified — that is where systemd-run --scope places the
    process. The cgroup v1 memory controller often points to a parent slice
    (user.slice) on hybrid systems and would aggregate unrelated activity.
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


def find_docker_cgroup(container_id: str) -> Optional[Path]:
    """Find cgroup path for a Docker container by id or name.

    Resolves the full container id via `docker inspect` then checks the standard
    cgroup layouts used by Docker on systemd hosts (cgroupfs and systemd driver).
    """
    try:
        full_id = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.Id}}", container_id],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        full_id = container_id

    candidates = [
        CGROUP_ROOT / f"system.slice/docker-{full_id}.scope",
        CGROUP_ROOT / f"docker/{full_id}",
        CGROUP_ROOT / f"system.slice/docker.service/docker/{full_id}",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fallback: search for the id as a directory name.
    if CGROUP_ROOT.exists():
        pattern = re.compile(re.escape(full_id))
        for root, dirs, _ in os.walk(CGROUP_ROOT):
            for d in dirs:
                if pattern.search(d):
                    return Path(root) / d
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
