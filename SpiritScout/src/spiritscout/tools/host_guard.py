"""host 执行后端的宿主侧边界收口（Windows ACL）。

`host` 后端没有命名空间：Agent 与用户同权限跑在本机上。bwrap 能做的「整机只读 +
主目录遮蔽」在 Windows 上没有等价物，这里补两层**只作用于本次会话目录**的 ACL 手段，
不动宿主其它路径：

1. 会话目录去继承、只授权「当前用户 / SYSTEM / Administrators」——多用户机器上别的
   本地账户读不到本次会话的临时文件与证据。
2. 证据目录（`attachments/`、`artifacts/`）加 deny 写 ACE——Agent 自己也不能改写判定
   依据，「看到什么」与「报什么」不会事后被自家人改掉。

**这不是读隔离**：Agent 仍可读宿主任意可读路径（`.ssh`、项目源码、密钥库）。真正的
读限制需要低完整性令牌或 AppContainer 启动器（要先编译一个启动器再接管管道），不在
纯 Python 范围内；边界写在 `docs/08-当前阶段、边界与不足.md`。

`icacls` 失败不阻断执行：加固是尽力而为，失败原因随返回值交给调用方留痕。
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_IS_WINDOWS = os.name == "nt"

# 已经加固过的目录（同一进程内多次工具调用不必重复跑 icacls）
_hardened: set[str] = set()

_SYSTEM_SID = "S-1-5-18"
_ADMINS_SID = "S-1-5-32-544"     # BUILTIN\Administrators，不随系统语言变化
# 拒绝写数据 / 追加 / 删除 / 删子项——证据目录只允许新增由工具显式放行的文件
_DENY_WRITE = "(OI)(CI)(WD,AD,DE,DC)"


@dataclass
class HardeningReport:
    """一次加固的结果，供审计与测试断言。"""

    applied: bool = False
    workspace_locked: bool = False
    readonly_denied: list[str] = field(default_factory=list)
    skipped: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"applied": self.applied, "workspace_locked": self.workspace_locked,
                "readonly_denied": list(self.readonly_denied), "skipped": self.skipped}


def current_user_sid() -> str:
    """当前进程用户的 SID（本地化的账户名在不同语言系统上不可靠，SID 才是稳定的）。"""
    if not _IS_WINDOWS:
        return ""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    # 64 位句柄必须声明 restype/argtypes：不声明时 ctypes 按 c_int 返回，伪句柄会被
    # 截成 32 位，后面的 OpenProcessToken 拿到无效句柄而静默失败。
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.GetCurrentProcess.argtypes = ()
    advapi.OpenProcessToken.argtypes = (ctypes.c_void_p, ctypes.c_uint32,
                                       ctypes.POINTER(ctypes.c_void_p))
    advapi.OpenProcessToken.restype = ctypes.c_int
    advapi.GetTokenInformation.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                           ctypes.c_uint32,
                                           ctypes.POINTER(ctypes.c_uint32))
    advapi.GetTokenInformation.restype = ctypes.c_int
    advapi.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_wchar_p))
    advapi.ConvertSidToStringSidW.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    token = ctypes.c_void_p()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return ""
    try:
        size = ctypes.c_uint32(0)
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        if not size.value:
            return ""
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size,
                                          ctypes.byref(size)):
            return ""
        # TOKEN_USER 的第一个成员就是 SID 指针
        sid_ptr = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = ctypes.c_wchar_p()
        if not advapi.ConvertSidToStringSidW(ctypes.c_void_p(sid_ptr),
                                             ctypes.byref(text)):
            return ""
        try:
            return text.value or ""
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.CloseHandle(token)


def available() -> bool:
    """Windows 上且 icacls 可用。"""
    if not _IS_WINDOWS:
        return False
    return _icacls_ok()


def _icacls_ok() -> bool:
    """icacls 能否启动：不带参数调用会打印用法并以非 0 退出，所以只看能否执行。"""
    try:
        subprocess.run(["icacls"], capture_output=True, timeout=10,
                       creationflags=_no_window())
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _no_window() -> int:
    return 0x08000000 if _IS_WINDOWS else 0


def _run(args: list[str]) -> tuple[bool, str]:
    try:
        done = subprocess.run(["icacls", *args], capture_output=True,
                              timeout=30, creationflags=_no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    # icacls 按控制台代码页输出（中文系统是 cp936），用 mbcs 解才是人话
    encoding = "mbcs" if _IS_WINDOWS else "utf-8"
    text = (done.stdout + done.stderr).decode(encoding, "replace").strip()
    return done.returncode == 0, text


def harden(workspace_dir: Path, readonly: tuple[Path, ...] = ()) -> HardeningReport:
    """锁定会话目录 ACL 并把证据目录设为只读；同一目录只做一次。"""
    report = HardeningReport()
    if not _IS_WINDOWS:
        report.skipped = "非 Windows：host 后端在 POSIX 上用进程组隔离，未启用 ACL 收口"
        return report
    target = str(Path(workspace_dir).resolve())
    if target in _hardened:
        report.skipped = "已加固"
        report.workspace_locked = True
        return report
    sid = current_user_sid()
    if not sid or not _icacls_ok():
        report.skipped = "取不到当前用户 SID 或 icacls 不可用"
        return report
    ok, detail = _run([target, "/inheritance:r",
                       "/grant:r", f"*{sid}:(OI)(CI)F",
                       f"*{_SYSTEM_SID}:(OI)(CI)F",
                       f"*{_ADMINS_SID}:(OI)(CI)F"])
    if not ok:
        report.skipped = f"目录 ACL 锁定失败: {detail[:200]}"
        return report
    report.workspace_locked = True
    for directory in readonly:
        path = Path(directory)
        if not path.is_dir():
            continue
        # 只锁**已存在的证据文件**，不锁目录本身：目录级 deny 会连平台补投附件
        # （同一用户写 attachments/）一起挡掉，那等于把上行通道焊死。
        for item in sorted(path.rglob("*")):
            if not item.is_file() or item.is_symlink():
                continue
            done, message = _run([str(item), "/deny", f"*{sid}:(WD,AD,DE)"])
            if done:
                report.readonly_denied.append(str(item))
            else:
                report.skipped = (report.skipped + "; " if report.skipped else "") + \
                    f"只读 ACE 失败 {item.name}: {message[:120]}"
    _hardened.add(target)
    report.applied = True
    return report


def release(workspace_dir: Path, readonly: tuple[Path, ...] = ()) -> None:
    """撤销证据文件的 deny 写 ACE（目录锁定保留：它只收紧，父目录本就属于同一用户）。"""
    if not _IS_WINDOWS:
        return
    sid = current_user_sid()
    if not sid:
        return
    for directory in readonly:
        path = Path(directory)
        if path.is_dir():
            for item in sorted(path.rglob("*")):
                if item.is_file() and not item.is_symlink():
                    with contextlib.suppress(OSError):
                        _run([str(item), "/remove:d", f"*{sid}"])
    _hardened.discard(str(Path(workspace_dir).resolve()))


def describe_acl(path: Path) -> str:
    """当前 ACL 的可读画像，供测试与排查（不含敏感内容，只有 ACE）。"""
    if not _IS_WINDOWS:
        return ""
    ok, text = _run([str(Path(path).resolve())])
    return text if ok else ""


def _self_check() -> int:
    """手工验一下本机行为：python -m spiritscout.tools.host_guard"""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "session"
        evidence = root / "attachments"
        evidence.mkdir(parents=True)
        original = evidence / "evidence.txt"
        original.write_text("original", encoding="utf-8")
        report = harden(root, (evidence,))
        print("harden:", report.as_dict())
        code = 0
        try:
            original.write_text("tampered", encoding="utf-8")
            print("改写既有证据：成功（加固未生效）")
            code = 1
        except OSError as exc:
            print(f"改写既有证据：被拒绝 ✓ ({type(exc).__name__})")
        # 上传通道必须仍然可用：目录不锁，新文件写得进去
        fresh = evidence / "uploaded.txt"
        fresh.write_text("new", encoding="utf-8")
        print("新增附件（平台补投）：成功 ✓")
        release(root, (evidence,))
        with contextlib.suppress(OSError):
            original.write_text("ok", encoding="utf-8")
            print("撤销后改写：成功 ✓")
        print("ACL:")
        print(describe_acl(evidence))
        return code


if __name__ == "__main__":       # pragma: no cover —— 本机排查入口
    sys.exit(_self_check())
