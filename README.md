# 全自动打靶 · 灵枢（SpiritScout）本机工作区

> 上游项目：**[FLIAZ/SpiritScout](https://github.com/FLIAZ/SpiritScout)**（灵枢，多智能体渗透/CTF 系统）。
> 本仓库是它的工作区级超集：上游源码 + 本机免 Docker 启动器 + 便携包构建脚本 + 运行期经验沉淀导出。
> 上游的 issue、新功能与许可问题请提到上游仓库。

## 这个仓库里有什么

| 路径 | 作用 |
| --- | --- |
`SpiritScout/` | 产品本体。灵枢 v0.23.0，Python 3.11+，FastAPI Web 控制台 + 多 Agent 编排。详见 [SpiritScout/README.md](SpiritScout/README.md)
`start-local.ps1` | 本机启动器（不走 Docker）：依赖自检 → 导出执行后端与模型 key 环境变量 → 前台起 Web 控制台
`启动服务.cmd` | 双击入口，包一层 `start-local.ps1 -Port 8010`
`deploy-spiritscout.ps1` | Docker Desktop 一键部署（CTF 的 shell/python 工具硬依赖 bubblewrap，Windows 原生沙箱不可用时需要它）
`_work/build_release.py` | 组装「解压即用」便携包：内嵌 CPython 3.11 + site-packages + app + configs + data，再打 zip
`_work/validate_release.py` | 构建后冒烟：包内解释器导入、控制台起停
`experience-export/` | 113 条运行期沉淀的方法论洞察（已脱敏），来源与脱敏规则见该目录 README
`packages/`（未提交） | 构建产物落点：wheel / sdist / portable zip，通过 GitHub Release 分发

## 三十秒跑起来

```powershell
py -3.11 -m venv SpiritScout\.venv
SpiritScout\.venv\Scripts\python.exe -m pip install -e "SpiritScout[toolkit]"
copy SpiritScout\configs\system.example.yaml SpiritScout\configs\system.yaml
.\启动服务.cmd
```

浏览器打开 <http://127.0.0.1:8010>。关闭那个窗口即停止服务。

只要界面点一遍、不真解题：把 `SpiritScout/configs/models.mock.yaml` 复制成 `models.yaml`，
模拟模型是确定性应答、不消耗 token。

## 本仓库不包含什么（有意为之）

| 排除项 | 原因 | 怎么恢复 |
| --- | --- | --- |
`SpiritScout/.venv/` 918M | 依赖 | `pip install -e "SpiritScout[toolkit]"` |
`.spiritscout/`（两处，共 412M） | 运行期状态根：黑板、会话、审计报告、密钥库 `vault.db`/`vault.key`/`auth.key` | 不用恢复，首次运行自动重建 |
`SpiritScout/configs/models.yaml`、`agent_models.yaml` | 真实供应商端点与模型分配 | 从 `.example.yaml` / `.mock.yaml` 复制 |
`.env`、任何 `*.key`、`*.db` | 凭据与本地库 | 全局排除，见 `.gitignore` |
`__pycache__/`、`.ruff_cache/`、`.tools/chrome-mcp/npm-cache` 58M | 缓存 | 自动重建 |
`packages/` 751M、`_stage/` 224M | 构建产物与旧暂存 | `python _work/build_release.py` |
**本地靶场 `local-range/`** | 自建 CTF 判题平台与跑批工作目录，属于测试基础设施而非产品；其中 `work-*` 含真实 flag 与会话产物 | 不在本仓库，也不再维护 |
`评估报告.md` | 内部选型评估，含本地靶场的 flag 值与私有模型网关地址 | 不在本仓库 |
`Rotom/`、`AiScan-N/` | 第三方参考项目，非本仓库源码 | 见下方「参考过的项目」 |

## 参考过的项目（已从本工作区移除，仅作选型记录）

- **[JerryXie599/Rotom](https://github.com/JerryXie599/Rotom)** — 轻量比赛型 CTF Agent，Cairn 黑板架构。
- **[SecNN/AiScan-N](https://github.com/SecNN/AiScan-N)** — 只有 README，本体是闭源二进制，无法嵌入。

两者与本仓库代码零交叉引用（双向 grep 均无命中），需要时按上面的地址重新 clone。

## 发布产物

Release 只附纯 Python 包，不附便携包（便携包内嵌解释器与第三方依赖）：

- `spiritscout-0.23.0-py3-none-any.whl` — `pip install spiritscout-0.23.0-py3-none-any.whl`
- `spiritscout-0.23.0.tar.gz` — sdist

装好后直接 `python -m spiritscout --port 8010`；注意 `--config` 与模型注册表按**当前工作目录**
解析，从仓库外安装时需要显式传 `--config` 指向你自己的 `system.yaml`。

## 安全边界

- 默认执行后端是 `host`：工作目录锁定、环境变量白名单、超时杀进程树，但**没有文件系统读隔离**。
- Web 控制台默认只绑 `127.0.0.1`；非回环绑定且未启用管理员认证时拒绝启动，
  判据见 [`SpiritScout/src/spiritscout/web/app.py:61`](SpiritScout/src/spiritscout/web/app.py#L61)。
- 只在你自己有授权的靶标上使用。完整条款见 [SpiritScout/SECURITY.md](SpiritScout/SECURITY.md)
  与上游 README 的「许可与使用约定」。

## 许可

Apache-2.0，版权归上游项目所有，见 [SpiritScout/LICENSE](SpiritScout/LICENSE)。
