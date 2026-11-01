"""灵枢（SpiritScout）Web 控制台启动入口。

用法::

    python -m spiritscout [--config configs/system.yaml] [--host 127.0.0.1] [--port 8000]
    python -m spiritscout --set-admin-password [--admin-username 名字] [--if-missing]

会话创建、拓扑观测、编队与模型管理、报告与审计导出均在浏览器内完成。
``--set-admin-password`` 不启动服务，只把管理员密码以 scrypt 哈希写进工作区的
``admin.db``——首次启动时由启动脚本调用，命令行里从不出现明文。
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import socket
import sys
import threading
import time
from pathlib import Path

# litellm 导入期会同步联网拉模型价格表（3 次重试+退避，慢网实测 22s+，
# 且跑在事件循环上会把整个控制台冻住）；官方开关改用内置表。本网络下
# 远端表本来就永远拉不到、每次都回退同一份内置表，设此开关只是省掉
# 注定失败的网络往返（取值必须为 True，"1" 不生效）。须在任何
# litellm 导入前设置。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from spiritscout import __version__
from spiritscout.config import load_model_config, load_system_config
from spiritscout.core.exceptions import SpiritScoutError
from spiritscout.platform_support import force_utf8_streams


def _load_dotenv(path: Path) -> None:
    """读取 .env 补全缺失变量（真实环境变量优先，兼容 CRLF 与引号）。"""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _find_dotenv() -> Path | None:
    candidates = (Path.cwd() / ".env",
                  Path(__file__).resolve().parents[2] / ".env")
    return next((path for path in candidates if path.is_file()), None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spiritscout",
        description="灵枢（SpiritScout）渗透测试智能体系统 · Web 控制台")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default="configs/system.yaml",
                        help="系统配置 YAML 路径")
    parser.add_argument("--host", default=None,
                        help="绑定地址（默认取配置 web.host=127.0.0.1）")
    parser.add_argument("--port", type=int, default=None,
                        help="端口（默认取配置 web.port=8000）")
    parser.add_argument("--set-admin-password", action="store_true",
                        help="设置/重置控制台管理员密码后退出（只保存 scrypt 哈希）")
    parser.add_argument("--admin-username", default=None,
                        help=f"配合 --set-admin-password，默认 {DEFAULT_ADMIN_USERNAME}")
    parser.add_argument("--if-missing", action="store_true",
                        help="已有管理员账号时直接跳过（启动脚本用）")
    parser.add_argument("--password-stdin", action="store_true",
                        help="从标准输入读一行作为密码（自动化用，不做二次确认）")
    return parser


#: 默认管理员用户名，与 ``AdminStore.sync_from_env`` 的兜底一致。
DEFAULT_ADMIN_USERNAME = "spiritscout"
#: 首次设密的最短长度；更低的值等于把控制台敞开给局域网。
MIN_ADMIN_PASSWORD_LENGTH = 8
#: ``--set-admin-password`` 的「密码不合规/输入不一致」退出码。
EXIT_PASSWORD_REJECTED = 3


def set_admin_password(cfg, args: argparse.Namespace) -> int:
    """把管理员密码写进工作区 ``admin.db``（scrypt 加盐哈希，明文不落盘）。

    三种取密码的方式，按上下文自动选：``--password-stdin`` 读一行标准输入
    （自动化/测试）；交互终端走两次不回显的提示；既不是终端也没给 stdin 时
    只跳过——启动脚本首次拉起服务时 stdin 可能是管道，不该因此卡住启动。
    """
    from spiritscout.web import auth as web_auth

    store = web_auth.AdminStore(cfg.workspace.root)
    if args.if_missing and store.has_admins():
        print(f"[跳过] 已存在管理员账号（{store.db_path}），本次不改密码")
        return 0

    interactive = sys.stdin.isatty() and not args.password_stdin
    username = (args.admin_username or "").strip()
    if interactive and not username:
        username = input(f"管理员用户名 [{DEFAULT_ADMIN_USERNAME}]: ").strip()
    username = username or DEFAULT_ADMIN_USERNAME

    if args.password_stdin:
        password = confirm = sys.stdin.readline().rstrip("\r\n")
    elif interactive:
        print("设置控制台管理员密码：只保存 scrypt 哈希，明文不写入任何文件。")
        password = getpass.getpass("密码（输入不回显）: ")
        confirm = getpass.getpass("再输一次: ")
    elif args.if_missing:
        print("[跳过] 当前不是交互终端，未设置管理员密码；"
              "需要时运行 python -m spiritscout --set-admin-password")
        return 0
    else:
        print("[错误] 当前不是交互终端，请改用 --password-stdin 传入密码",
              file=sys.stderr)
        return EXIT_PASSWORD_REJECTED

    if password != confirm:
        print("[错误] 两次输入不一致，未写入", file=sys.stderr)
        return EXIT_PASSWORD_REJECTED
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        print(f"[错误] 密码至少 {MIN_ADMIN_PASSWORD_LENGTH} 个字符", file=sys.stderr)
        return EXIT_PASSWORD_REJECTED
    try:
        web_auth.validate_credentials(username, password)
    except SpiritScoutError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return EXIT_PASSWORD_REJECTED
    store.upsert(username, password)
    print(f"[完成] 管理员 {username} 已写入 {store.db_path}")
    print("       文件里只有 scrypt 加盐哈希；忘记密码删掉 admin.db 再设一次即可。")
    return 0


#: 状态行间隔（秒）。太密会把窗口刷满、看不出趋势；太疏又等不上。
STATUS_INTERVAL = 60.0


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """端口此刻是否收得住 TCP 连接。

    用真实连接判断「浏览器能打开了」，而不是猜一个固定秒数——首次启动要建库、
    装依赖、预热模型，花多久说不准：猜短了提示是假的，猜长了白等。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _duration(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _status_line(app, uptime: float) -> str:
    """一行状态：跑了多久、多少个会话在动、吃了多少内存。

    psutil 不是核心依赖（``pip install -e`` 不会带它），缺了只少这两项，
    状态行照样打。
    """
    total = running = 0
    try:
        sessions = app.state.manager.list()
        total = len(sessions)
        running = sum(1 for s in sessions if getattr(s, "status", "") == "running")
    except Exception:          # noqa: BLE001 - 报状态出错不该把服务带崩
        pass
    parts = [f"已运行 {_duration(uptime)}", f"会话 {total}（运行中 {running}）"]
    try:
        import psutil
    except ImportError:
        pass
    else:
        with contextlib.suppress(Exception):   # 读不到内存就只少这一项
            parts.append(f"内存 {psutil.Process().memory_info().rss / 1024 / 1024:.0f} MB")
    return "[状态] " + " · ".join(parts)


def _watch_console(server, app, host: str, port: int, timeout: float = 90.0) -> None:
    """等端口真能连上后提示一次，之后按间隔报状态。

    跑在守护线程里，主线程留给 ``server.run()``——信号处理只能在主线程装，
    挪过来的话 Ctrl+C 会直接抛 ``signal only works in main thread``。
    """
    deadline = time.monotonic() + timeout
    ready = False
    while time.monotonic() < deadline and not server.should_exit:
        if getattr(server, "started", False) and _port_open(host, port):
            ready = True
            break
        time.sleep(0.2)
    if server.should_exit:
        return
    if ready:
        print(f"\n[就绪] 浏览器可以打开了: http://{host}:{port}")
        print(f"       每 {int(STATUS_INTERVAL)} 秒报一次状态；Ctrl+C 停止\n")
    else:
        print(f"[提示] {timeout:.0f} 秒内还没连上 {host}:{port}，"
              "可能仍在初始化，稍后刷新试试", file=sys.stderr)
    begun = time.monotonic()
    while not server.should_exit:
        time.sleep(STATUS_INTERVAL)
        if server.should_exit:
            return
        print(_status_line(app, time.monotonic() - begun))


def main(argv: list[str] | None = None) -> int:
    # 英文 Windows 的重定向输出可能默认 cp1252，中文帮助/错误信息也须能输出。
    force_utf8_streams()
    args = build_parser().parse_args(argv)
    dotenv = _find_dotenv()
    if dotenv:
        _load_dotenv(dotenv)      # 忘记管理员凭据时改 .env 重启即可恢复
    try:
        cfg = load_system_config(args.config)
        if args.set_admin_password:
            return set_admin_password(cfg, args)
        models = load_model_config(cfg.models_config_path)
    except SpiritScoutError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    import uvicorn

    from spiritscout.web import create_app

    host = args.host or cfg.web.host
    port = args.port or cfg.web.port
    # 命令行覆盖不只传给 uvicorn；应用内部的认证策略和生成的
    # 同源边界也必须看到最终绑定值。
    cfg.web.host = host
    cfg.web.port = port
    try:
        app = create_app(cfg, models,
                         max_concurrent=cfg.web.max_concurrent_sessions)
    except SpiritScoutError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    # 预热 litellm：把 ~2s 的库导入成本从「首次调用途中」挪到启动时
    # （调用在事件循环上，冷导入曾把控制台冻 22s+）；失败留待调用路径
    # 原生报错，不阻断启动
    try:
        import litellm  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"[警告] litellm 预热失败（首次调用时重试）：{exc}", file=sys.stderr)
    auth_note = ("管理员登录已启用" if app.state.auth_enabled
                 else "未配置管理员，仅回环地址可访问")
    print(f"灵枢 Web 控制台: http://{host}:{port}  "
          f"({auth_note}，并发上限 {cfg.web.max_concurrent_sessions}，"
          "Ctrl+C 停止)")
    # 用可控的 Server 顶掉 uvicorn.run()：后者一进去就阻塞，窗口从此哑着，
    # 只留上面这行「控制台: http://…」——可打出时监听还没建起来，照着点会连不上。
    # 这里另开守护线程，等端口真能收连接再喊一次，之后定时报状态。
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning"))
    threading.Thread(target=_watch_console, args=(server, app, host, port),
                     name="console-watch", daemon=True).start()
    server.run()
    print("[停止] 服务已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
