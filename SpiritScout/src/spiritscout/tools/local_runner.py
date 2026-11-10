"""本地工具运行器：复制到暂存目录里跑，跑完把原目录还原成用之前的样子。

要求只有一句：**用完之后不得有残留**。做法是把风险按顺序压掉：

1. **不在原目录里跑**：工具目录先整份复制到 `<workspace>/local-tools/runs/<id>/work`，
   可执行文件、工作目录、临时目录、HOME/APPDATA 全部指到这份副本里。绝大多数
   "绿色版"工具只会往 cwd 和 %TEMP% 写东西，于是它们写的是副本。
2. **原目录前后对账**：跑之前记一份清单（相对路径 → 大小/mtime），跑完再记一份。
   新增的路径删掉、改动或删掉的路径从副本里复制回去（副本就是跑之前的原样）。
3. **跑完必删**：暂存目录、临时目录、假 HOME 在 `finally` 里整棵删掉；上一次崩溃
   留下的残壳在每次运行前顺手清掉（`sweep_runs`），不会越攒越多。
4. **说不清就不跑**：目录大到装不进暂存（超过 max_stage_mb）直接拒跑并说明原因，
   而不是"先跑跑看"——保证不了干净就不动用户的目录。

返回的是结构化对账结果：`clean` 表示前后清单完全一致（残留已清、改动已还原），
`removed/restored/missing` 说明这次到底动了什么，`stage_removed` 说明副本已销毁。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

RUN_DIRNAME = "runs"
# 超过这个时间还没删掉的暂存目录视作上一次崩溃的残壳
STALE_SECONDS = 1800
OUTPUT_LIMIT = 20000


class LocalToolError(RuntimeError):
    """本地工具不能安全运行（路径越界、太大、找不到解释器等）。"""


def runs_root(workspace: str | Path) -> Path:
    return Path(workspace) / "local-tools" / RUN_DIRNAME


def _real(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def inside(path: str | Path, roots: list[str]) -> bool:
    """路径是否真的落在用户设置的目录里（用真实路径判，符号链接绕不出去）。"""
    target = _real(path)
    for root in roots:
        base = _real(root)
        if target == base or target.startswith(base + os.sep):
            return True
    return False


def manifest(root: Path) -> dict[str, tuple[int, int]]:
    """目录清单：相对路径 → (大小, mtime_ns)。只记文件，空目录由删除逻辑兜底。"""
    out: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:            # 正好被删/被占用：这一步当作没有它
                continue
            out[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return out


def total_bytes(items: dict[str, tuple[int, int]]) -> int:
    return sum(size for size, _ in items.values())


def sweep_runs(workspace: str | Path, *, stale_seconds: float = STALE_SECONDS) -> list[str]:
    """清掉超时没删掉的暂存目录；返回确实清掉的路径（崩溃残壳不会长期堆着）。"""
    base = runs_root(workspace)
    if not base.is_dir():
        return []
    removed: list[str] = []
    now = time.time()
    for child in base.iterdir():
        try:
            if not child.is_dir():
                continue
            if now - child.stat().st_mtime < stale_seconds:
                continue
        except OSError:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed.append(str(child))
    return removed


def _command(path: Path, args: list[str]) -> list[str]:
    """按后缀选解释器：脚本类工具交给对应解释器，二进制直接起。"""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(path), *args]
    if suffix == ".ps1":
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(path), *args]
    if suffix in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(path), *args]
    if suffix == ".sh":
        return ["bash", str(path), *args]
    if suffix == ".jar":
        return ["java", "-jar", str(path), *args]
    return [str(path), *args]


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """超时收口：连子孙一起收，别让工具的子进程在暂存目录删掉之后还在写。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), 9)      # type: ignore[attr-defined]
        except (OSError, AttributeError):
            proc.kill()


def _snapshot_env(work: Path) -> dict[str, str]:
    """把临时目录与"家目录"整体搬进副本：写哪儿都落在要删的那棵树里。"""
    home = work / "_home"
    tmp = work / "_tmp"
    for folder in (home, tmp, home / "AppData" / "Roaming", home / "AppData" / "Local",
                   home / ".config", home / ".cache", home / ".local" / "share",
                   home / "pycache"):
        folder.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp),
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        # 解释器自己别再往副本里写 __pycache__（本来也会随副本删掉，省一步）
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(home / "pycache"),
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def _trim(text: bytes) -> str:
    try:
        decoded = text.decode("utf-8", "replace")
    except Exception:                                  # pragma: no cover - 兜底
        return ""
    return decoded[-OUTPUT_LIMIT:]


def run_local_tool(tool: dict[str, Any], args: list[str] | None, *,
                   workspace: str | Path, roots: list[str],
                   timeout: float = 180.0, max_stage_mb: int = 512) -> dict[str, Any]:
    """把索引里的一个工具跑在副本里，跑完还原原目录并销毁副本。"""
    target = Path(str(tool.get("path") or ""))
    name = str(tool.get("name") or target.stem or "local-tool")
    if not target.is_file():
        raise LocalToolError(f"工具文件不存在: {target}")
    if not inside(target, roots):
        raise LocalToolError(f"工具不在设置的目录内，拒绝执行: {target}")
    source = Path(os.path.realpath(str(target.parent)))

    before = manifest(source)
    size = total_bytes(before)
    if size > max_stage_mb * 1024 * 1024:
        raise LocalToolError(
            f"工具目录 {source} 约 {size / 1048576:.0f} MB，超过暂存上限 {max_stage_mb} MB；"
            "无法保证跑完恢复原样，已拒绝执行（可在设置里调大 max_stage_mb）")
    rel = target.relative_to(target.parent) if target.is_relative_to(target.parent) else Path(target.name)

    sweep_runs(workspace)
    run_dir = runs_root(workspace) / f"run-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    work = run_dir / "work"
    stage_removed = False
    timed_out = False
    started = time.perf_counter()
    outcome: dict[str, Any] = {}
    process: subprocess.Popen[bytes] | None = None
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, work, symlinks=False)
        staged = work / rel
        if not staged.is_file():
            raise LocalToolError(f"副本里找不到可执行文件: {rel}")
        env = _snapshot_env(work)
        cmd = _command(staged, [str(a) for a in (args or [])])
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            cmd, cwd=str(work), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=creationflags, start_new_session=os.name != "nt")
        try:
            out, err = process.communicate(timeout=max(1.0, float(timeout)))
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(process)
            try:
                out, err = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:      # pragma: no cover - 极端情况
                out, err = b"", b""
        duration = (time.perf_counter() - started) * 1000
        outcome = {
            "ok": process.returncode == 0 and not timed_out,
            "returncode": process.returncode,
            "stdout": _trim(out), "stderr": _trim(err),
            "duration_ms": round(duration, 1), "timed_out": timed_out,
        }
    finally:
        # 先对账再删副本：副本就是跑之前的原样，还原时要用它
        try:
            after = manifest(source)
            added = sorted(set(after) - set(before))
            missing = sorted(set(before) - set(after))
            changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
            removed: list[str] = []
            restored: list[str] = []
            for name in added:                     # 新增的：删掉（深的先删，目录才好清）
                victim = source / name
                try:
                    victim.unlink()
                    removed.append(name)
                except OSError:
                    pass
            for name in sorted([*changed, *missing]):
                origin = work / name
                if not origin.is_file():           # 副本里没有就真还原不了，如实报告
                    continue
                dest = source / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, dest)         # copy2 带上 mtime，清单能对上
                restored.append(name)
            # 新增文件留下的空目录也要清掉
            for name in added:
                parent = (source / name).parent
                while parent != source and parent.is_dir():
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
            final = manifest(source)
            clean = final == before
            outcome.update({
                "clean": clean,
                "removed": removed,
                "restored": restored,
                "unrestored": sorted(set(final) - set(after)) if not clean else [],
                "diff": {"added": added, "changed": changed, "missing": missing},
            })
        except Exception as exc:                    # noqa: BLE001 —— 对账失败也要把副本删掉
            outcome.setdefault("clean", False)
            outcome["verify_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
            stage_removed = not run_dir.exists()

    outcome.update({
        "tool": name,
        "stage_removed": stage_removed,
        "stage_bytes": size,
        "workdir": "已在运行结束后删除",
        "mode": "staged",
    })
    return outcome
