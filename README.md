# 全自动打靶 · 灵枢（SpiritScout）本机工作区

> 上游项目：**[FLIAZ/SpiritScout](https://github.com/FLIAZ/SpiritScout)**（灵枢，多智能体渗透/CTF 系统）。
> 本仓库是它的工作区级超集：上游源码 + 本机免 Docker 启动器 + 便携包构建脚本 + 运行期经验沉淀导出。
> 上游的 issue、新功能与许可问题请提到上游仓库。

## 这个仓库里有什么

| 路径 | 作用 |
| --- | --- |
`SpiritScout/` | 产品本体。灵枢 v0.23.1，Python 3.11+，FastAPI Web 控制台 + 多 Agent 编排。详见 [SpiritScout/README.md](SpiritScout/README.md)
`start-local.ps1` | 本机启动器（不走 Docker）：环境与依赖自检（缺运行依赖自动 `pip install`，缺 venv/pip/解释器版本只给命令不动手）→ 导出执行后端与模型 key 环境变量 → 前台起 Web 控制台。`-NoInstall` 只报告不装
`启动服务.cmd` | 双击入口，包一层 `start-local.ps1 -Port 8010`
`deploy-spiritscout.ps1` | Docker Desktop 一键部署（CTF 的 shell/python 工具硬依赖 bubblewrap，Windows 原生沙箱不可用时需要它）
`_work/build_release.py` | 组装「解压即用」便携包：内嵌 CPython 3.11 + site-packages + app + configs + data，再打 zip
`_work/validate_release.py` | 打包前的冒烟：包内解释器导入、沙箱解释器探测、配置数据落点、控制台真起停；跑完清掉它在 `data\` 留下的运行数据，好让下一步打出一个没被人点开过的包
`experience-export/` | 113 条运行期沉淀的方法论洞察（已脱敏），来源与脱敏规则见该目录 README
`packages/`（未提交） | 构建产物落点：wheel / sdist / portable zip，通过 GitHub Release 分发

## 三十秒跑起来

```powershell
py -3.11 -m venv SpiritScout\.venv
copy SpiritScout\configs\system.example.yaml SpiritScout\configs\system.yaml
.\启动服务.cmd
```

只有 venv 需要你亲手建（装在哪、用哪个解释器由你定）；建好后双击启动，缺的运行依赖
与可选工具包由 `start-local.ps1` 自己 `pip install`，首次要几分钟。不想让它联网装东西就
手动跑 `powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -NoInstall`，只报命令。

浏览器打开 <http://127.0.0.1:8010>。关闭那个窗口即停止服务。

只要界面点一遍、不真解题：把 `SpiritScout/configs/models.mock.yaml` 复制成 `models.yaml`，
模拟模型是确定性应答、不消耗 token。

## 本仓库不包含什么（有意为之）

| 排除项 | 原因 | 怎么恢复 |
| --- | --- | --- |
`SpiritScout/.venv/` 918M | 依赖 | `pip install -e "SpiritScout[toolkit]"` |
`SpiritScout/.spiritscout/` | 现行运行期状态根：启动器把 cwd 设在 `SpiritScout\`，而 `configs/system.yaml` 里 `workspace.root: .spiritscout` 是相对路径，所以黑板、会话、审计报告、以及可能出现的密钥库 `vault.db`/`vault.key`/`auth.key` 都落在这里 | 不用恢复，首次运行自动重建 |
仓库根那份 `.spiritscout/`（12M） | 早期以仓库根为工作目录跑出来的**游离状态**，属于 0.12.9 世代（2026-10-27~28），里面是已下线本地靶场的真实 flag 值与拓扑记录 | 已移出工作区（不在本仓库，也不再维护）；条数、层级、时间范围等脱敏清点见 [experience-export/legacy-state-0.12.9.json](experience-export/legacy-state-0.12.9.json) |
`SpiritScout/configs/models.yaml`、`agent_models.yaml` | 真实供应商端点与模型分配 | 从 `.example.yaml` / `.mock.yaml` 复制 |
`.env`、任何 `*.key`、`*.db` | 凭据与本地库 | 全局排除，见 `.gitignore` |
`__pycache__/`、`.ruff_cache/`、`.tools/chrome-mcp/npm-cache` 58M | 缓存 | 自动重建 |
`packages/` 941M | 构建产物落点：227M 便携包 zip + 709M 打包前的暂存目录 + 2.5M 的 0.16.x 存档 | `python _work/build_release.py`（三步顺序见 [packages/README.md](packages/README.md)）。旧的 0.23.0 产物与 `_stage/` 224M 旧暂存已删：wheel/sdist 在 v0.23.0 Release 上还能下载，0.23.0 便携包从未作为资产发布、内容又被 0.23.1 完全覆盖（两代 `site-packages` 只差一个过期元数据，老冻结清单里 130 个依赖新包 130/130 都在） |
**本地靶场 `local-range/`** | 自建 CTF 判题平台与跑批工作目录，属于测试基础设施而非产品；其中 `work-*` 含真实 flag 与会话产物 | 不在本仓库，也不再维护 |
`评估报告.md` | 内部选型评估，含本地靶场的 flag 值与私有模型网关地址 | 不在本仓库 |

## 发布产物

Release 附三种包，按需取用：

- `spiritscout-0.23.1-py3-none-any.whl` — 二进制轮包。带 CTF 工具箱要用
  `pip install "spiritscout[toolkit] @ file:///…whl"` 这种 PEP 508 直接引用形式；
  写成 `xxx.whl[toolkit]` 会被 pip **静默丢弃 extras**，一个工具箱依赖都不装且不报错。
- `spiritscout-0.23.1.tar.gz` — sdist 源码分发，含 `src/` 与 `tests/`
- `SpiritScout-0.23.1-portable.zip`（约 227MB，解压后 613MB）— 免安装便携包：内嵌 CPython 3.11 与
  全部依赖，解压后双击 `1-启动服务.bat` 即用，目标机不需要装 Python，路径带中文也没问题。
  自己重建，按这个顺序三步：`python _work/build_release.py`（只组装暂存目录）→
  `python _work/validate_release.py`（把包当别人拿到手那样冒烟跑一遍，跑完清掉它在
  `data\` 里留下的运行数据）→ `python _work/build_release.py --zip-only`（打 zip）。
  先验后打是有意的：冒烟会把控制台真起一次，先打 zip 就把「被人点开过一次」的包发出去。

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
