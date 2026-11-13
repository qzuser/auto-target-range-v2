# 全自动打靶 · 灵枢（SpiritScout）本机工作区

> 上游项目：**[FLIAZ/SpiritScout](https://github.com/FLIAZ/SpiritScout)**（灵枢，多智能体渗透/CTF 系统）。
> 本仓库是它的工作区级超集：上游源码 + 本机免 Docker 启动器 + 便携包构建脚本 + 运行期经验沉淀导出。
> 上游的 issue、新功能与许可问题请提到上游仓库。

## 这个仓库里有什么

| 路径 | 作用 |
| --- | --- |
`SpiritScout/` | 产品本体。灵枢 v0.24.3，Python 3.11+，FastAPI Web 控制台 + 多 Agent 编排。详见 [SpiritScout/README.md](SpiritScout/README.md)
`start-local.ps1` | 本机启动器（不走 Docker）：环境与依赖自检（缺运行依赖自动 `pip install`，缺 venv/pip/解释器版本只给命令不动手）→ 导出执行后端与模型 key 环境变量 → 前台起 Web 控制台。首次启动会先让你设管理员密码（输两遍、不回显，只存 scrypt 哈希进 `admin.db`）。`-NoInstall` 只报告不装；装依赖默认走**清华 PyPI 镜像**，`-PipIndex official` 换官方源
`启动服务.cmd` | 双击入口，包一层 `start-local.ps1 -Port 8010`
`deploy-spiritscout.ps1` | Docker Desktop 一键部署（CTF 的 shell/python 工具硬依赖 bubblewrap，Windows 原生沙箱不可用时需要它）
`_work/build_release.py` | 组装「解压即用」便携包：内嵌 CPython 3.11 + site-packages + app + configs + data，再打 zip
`_work/validate_release.py` | 打包前的冒烟：包内解释器导入、沙箱解释器探测、配置数据落点、控制台真起停；跑完清掉它在 `data\` 留下的运行数据，好让下一步打出一个没被人点开过的包
`experience-export/` | 运行期经验沉淀的**脱敏快照**（`experience-insights.json`，条数见文件里的 `total`）：`export_experience.py` 从 `SpiritScout/.spiritscout/experience.db` 导出，pre-commit 钩子保证每次提交都把它一起带上。装钩子：`python experience-export/install_hook.py`。细节见该目录 README
`packages/`（未提交） | 构建产物落点：wheel / sdist / portable zip，通过 GitHub Release 分发

## 三十秒跑起来

```powershell
py -3.11 -m venv SpiritScout\.venv
.\启动服务.cmd
```

只有 venv 需要你亲手建（装在哪、用哪个解释器由你定）；建好后双击启动，缺的运行依赖
与可选工具包由 `start-local.ps1` 自己 `pip install`，首次要几分钟。不想让它联网装东西就
手动跑 `powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -NoInstall`，只报命令。

装依赖的源默认是**清华 PyPI 镜像**（`https://pypi.tuna.tsinghua.edu.cn/simple`），
国内直连官方站常常几十 KB/s；镜像没同步好或想走官方源时，`.\start-local.ps1 -PipIndex official`，
换别的镜像 `-PipIndex https://mirrors.aliyun.com/pypi/simple/`，也可以设环境变量
`SPIRITSCOUT_PIP_INDEX`。镜像装不下来时脚本会自动退官方源重试一次并打印换了源。
只想看当前解析出哪个源、不动手：`.\start-local.ps1 -ShowPipIndex`。

浏览器打开 <http://127.0.0.1:8010>。关闭那个窗口即停止服务。
端口来自双击入口里的 `-Port 8010`（它转成 `--port` 覆盖 `configs/system.yaml` 的 `web.port`；
那份配置里写的是 8000，只是给 `launch.cmd` / `launch.sh` 这类不带参启动用的，两个数字不一样是正常的）。

第一次启动会先问管理员密码：用户名直接回车就是 `master`，密码输两遍（不回显）；**长度不限**，
一位和整句话都收。设完明文会在**这个终端显示一次**方便当场记下来，之后重启、日志、界面都不再
显示，库里只有 scrypt 加盐哈希（明文不进命令行、不落盘）。回车两次就是不设——控制台只绑
`127.0.0.1`，别的机器进不来，`auth_mode: none` 下不设也能直接进。想改密码：
`SpiritScout\.venv\Scripts\python.exe -m spiritscout --set-admin-password`，或删掉
`SpiritScout/.spiritscout/admin.db` 再启动一次。

`configs/system.yaml` **已随仓库提交，并且是跑通过的配置**，新克隆下来直接启动就行；
不要再拿 `copy system.example.yaml system.yaml` 覆盖它——example 是带注释的最小模板，
覆盖会冲掉本机 MCP 名单和沙箱后端设置，两份的差异见下一节。

模型注册表 `configs/models.yaml` 不在仓库里，缺了服务照样起（[`SpiritScout/src/spiritscout/web/modelcfg.py:81`](SpiritScout/src/spiritscout/web/modelcfg.py#L81)
对不存在的文件直接返回空列表），但开工会被拦：注册表为空时会话不启动并提示「请先配置至少一个模型」
（[`SpiritScout/src/spiritscout/web/sessions.py:811`](SpiritScout/src/spiritscout/web/sessions.py#L811)）。
在 Web「模型」页加供应商即可，程序会自己把这个文件写出来。
同目录的 `agent_models.yaml`（按 Agent 指派模型）**没有 `.example` 模板**，别被「从 example 复制」的习惯带偏：
它由 Web「编队」页维护，手工写 `assignments: {}` 与 `naming:` 即可，缺了只是全跟随档位路由。

只要界面点一遍、不真解题：把 `SpiritScout/configs/models.mock.yaml` 复制成 `models.yaml`，
模拟模型是确定性应答、不消耗 token。

## 本地小模型：怎么配、能解什么

没有 API 额度也能跑：LM Studio（或 Ollama）起一个 OpenAI 兼容端点，灵枢直接对接。
8 GB 显存这一档实测下来，配置对错比模型大小更决定成败。

### 推理服务：两套，自动切换

优先用 LM Studio 的服务（`lms server start`）；它起不来时用 LM Studio 自带的
llama-server 兜底。兜底命令有个必须注意的前提——**要在后端目录下运行**，否则报
`0xC0000135`（缺 DLL）：

```powershell
cd $env:USERPROFILE\.lmstudio\extensions\backends\llama.cpp-win-x86_64-nvidia-cuda12-avx2-*
$env:PATH = "$PWD;$env:USERPROFILE\.lmstudio\extensions\backends\vendor\win-llama-cuda12-vendor-v2;$env:PATH"
llama-server.exe -m <Qwen3.5-9B-Q4_K_M.gguf> -a qwen3.5-9b -c 16384 -ngl 99 `
  --host 127.0.0.1 --port 1234 -np 1 --reasoning-budget 0
```

CUDA 运行时在 `vendor\win-llama-cuda12-vendor-v2`，不加进 PATH 也是同一个报错。

### 配置要点（8 GB 显存）

| 项 | 取值 | 为什么 |
|---|---|---|
| 模型 | `qwen3.5-9b`（Q4_K_M，5.24 GB） | 这一档唯一能完整走完解题环的；见下方实测表 |
| 上下文 | 16384（单模型独占时可到 32768） | 32k 单槽实测占 7305/8151 MiB 能跑；**同时有别的模型占显存就绑不上**，退 16384 |
| 单次输出 | 1024~2048 | 太大会输出半截 JSON 判失败，太小写不完一段脚本 |
| 并发 | 1（`--parallel 1`） | LM Studio 会把总上下文按并行槽平分，4 槽时每个请求只剩 1/4 |
| 思考 | 关闭（`--reasoning-budget 0`）或 `reasoning_effort: low` | 思考型模型会把输出额度全烧在推理上，正文为空 |
| 显存纪律 | **同时只加载一个模型** | 两个实例抢显存是本机最常见的「提交后一直转圈」 |

### 实测能力边界（本机 8 GB 显存，qwen3.5-9b）

| 题型 | 结果 |
|---|---|
| 西湖论剑 2021 IoT base64 逆向（自定义字母表） | ✅ 9 次工具调用、约 9.5 万 token 解出 |
| 三层 base64（有现成工具 `decode_chain`） | ✅ 3 步、4–5 分钟 |
| 网上 RSA 真题（需要读懂变量覆盖） | ❌ 65k token 未解出 |
| Knapsack（子集和 + AES） | ❌ 调用链崩（非法 JSON + 500） |
| PNG / zip / web SQLi（单 agent 模式） | ⚠️ 给模板能过，不给模板不行 |

**规律：有现成工具、流程明确的题能解；需要模型自己想通关键点的题，基本解不出。**
同题对照过的模型：`bonsai-27b` Q1_0 正文全空、`gemma-4-12b` 16k 上下文直接 OOM、
`qwen2.5-coder-7b` 报错后重发同一命令打转——不是参数量问题，是量化与管线问题。

### 常见问题

- **提交后一直转圈、token 不涨**：多半有两个模型实例在抢显存。卸掉重载一个。
- **窗口里没有日志**：确认 bat 是 **CRLF 换行**（cmd 按字节读，LF 会让中文行错位）。
- **想让它做更难的题**：只有两条路有效——给它现成工具，或在任务描述里写清步骤。
  单纯调温度、加资料都验证过无效。

## 桌面版：带自己窗口的那种开法

不想开黑窗口、也不想在浏览器标签页里跑控制台，就双击 **`灵枢桌面版.exe`**：左边是环境自检
与一键修复，右边是嵌在本窗口里的控制台页面（WebView2，不是外部标签页），关窗口即停服务。

exe 不在仓库里（`.gitignore` 挡了），要么从 release 附件拿，要么自己编一次：

```powershell
powershell -ExecutionPolicy Bypass -File SpiritScout\launcher\build-desktop.ps1
```

首次会下 WebView2 SDK（约 8 MB，缓存在 `SpiritScout/launcher/.cache/`，之后离线可用：
加 `-SkipDownload`）。编译用 Windows 自带的 `csc.exe`，**不需要装 .NET SDK**；产物是
一个约 824 KB 的 exe，内嵌浏览器要的三个 DLL 以资源形式塞在里面，首次运行时自己解到
`%LOCALAPPDATA%\SpiritScout\lib`（那目录写不进去就退程序目录、再退临时目录）。

它替你做的判断：

- **环境自检/一键修复**：调 `SpiritScout/scripts/bootstrap.py`——挑 3.11+ 解释器、建 venv、
  补 pip、装依赖（清华 → 阿里 → 官方逐源重试），缺什么补什么，不用记命令。
- **端口自动让开**：8010 被占就 8011、8012 往下找，不必改配置。
- **起停成对**：点「停止」或关窗口都会把服务进程树一起收掉，不留孤儿占着端口。
- **出问题留证据**：日志写 `logs\desktop-<日期>.log`；真崩了弹窗并把堆栈写进
  `crash-<时间>.log`，不用对着「双击没反应」猜。
- **没有 WebView2 运行时**：自动退到 Edge 的 `--app=` 独立窗口，照样能用。

命令行那条路（`启动服务.cmd` + `start-local.ps1`）没变，桌面版只是给它套了个窗口；
两者不要同时开同一个端口。

## 便携版：连 Python 都不用装

上面的桌面版要目标机器上有 Python 3.11+。要交给一台干净机器（或者塞进 U 盘），就打成便携版：
内嵌 python.org 的 embeddable 运行时 + 装好的依赖 + exe 摆进同一个目录。

```powershell
python -m build --outdir dist SpiritScout
powershell -ExecutionPolicy Bypass -File SpiritScout\launcher\build-portable.ps1
```

产物 `dist-portable\灵枢便携版-<版本>\` 约 334 MB，`desktop.json` 指路、`configs\` 只有模板、
`py\` 里是解释器和 95 个依赖。整份目录拷到别的机器，解压双击 `灵枢桌面版.exe` 就开——
不装 Python、不联外网也能起来（调模型当然还要网）。


## 两份 system 配置：为什么不是简单地「照 example 覆盖」

仓库同时提交 [`SpiritScout/configs/system.yaml`](SpiritScout/configs/system.yaml)（本机现行）
和 [`system.example.yaml`](SpiritScout/configs/system.example.yaml)（上游最小模板）。
把两份按 `段.键` 摊平到叶子（列表按下标展开）分别是 105 与 93 个键。
两者有意保留差异，diff 一遍的结果记在这里：

| 只在哪份里写出 | 键 | 影响 |
| --- | --- | --- |
| 只有 `system.yaml` | `executor.sandbox_backend: auto` | 代码默认也是 `auto`（[`settings.py:129`](SpiritScout/src/spiritscout/config/settings.py#L129)），写出来是为了看得见；不写不会变行为 |
| 只有 `system.yaml` | `ida`、`yakit` 两个 MCP 服务，以及每个服务的 `transport`/`timeout` | example 里没有这两项，覆盖即失去逆向与 Yakit 工具；就算手工搬过去，`timeout` 不写会退回 180 秒默认（[`settings.py:190`](SpiritScout/src/spiritscout/config/settings.py#L190)），`ida` 分析大型二进制要 600 秒 |
| 只有 `example` | `bus.connect_timeout_seconds`、`bus.namespace`、`bus.redis_url_env`、`bus.shared_request_rps` | 四个都有同名代码默认且数值与 example 一致（[`settings.py:82-85`](SpiritScout/src/spiritscout/config/settings.py#L82)），现行配置不缺功能 |
| 只有 `example` | `web.admin_username_env`、`web.admin_password_env` | 同上，[`settings.py:165-168`](SpiritScout/src/spiritscout/config/settings.py#L165) 的默认就是这两个环境变量名 |

一个容易踩的默认值差异：`mcp_servers[].risk_by_action` 的**代码默认是 `False`**
（[`settings.py:192`](SpiritScout/src/spiritscout/config/settings.py#L192)），example 却给 playwright/chrome 显式写了 `true`。
`system.yaml` 里 playwright/chrome 同样写了 `true`，所以两者一致；但 `ida`/`yakit` 没写，走 `False`。
`yakit` 靠 `default_risk: intrusive` 兜住危险审批，`ida` 是只读工具，均无需改。
要在别的 MCP 服务上拿到「逐次声明本次行为」的审批，必须显式写 `risk_by_action: true`，不能指望默认。

## 发布产物

Release 上按需取：

| 附件 | 给谁用 |
| --- | --- |
| `spiritscout-<版本>-single-win64.exe` | **单文件版（约 132 MB）**：一个 exe 把 Python 运行时挂在尾巴上，拷过去双击就开，不装 Python、不带源码、不解压 |
| `spiritscout-desktop-<版本>-win64.exe` | Windows 桌面版（约 828 KB）：自带窗口，但机器上要有 Python 3.11+ 与一份仓库 |
| `spiritscout-<版本>-portable-win64.zip` | **便携版（约 150 MB）**：内嵌 Python 与 95 个依赖，解压双击 `灵枢桌面版.exe` 就用，目标机什么都不装 |
| `spiritscout-<版本>-py3-none-any.whl` | `pip install` 用。带 CTF 工具箱要写成 `pip install "spiritscout[toolkit] @ file:///…whl"`——写成 `xxx.whl[toolkit]` 会被 pip **静默丢弃 extras**，一个工具箱依赖都不装还不报错 |
| `spiritscout-<版本>.tar.gz` | sdist：源码 + `scripts/` + `skills/` 文本素材 + 配置模板 |
| `spiritscout-<版本>.zip` | 整仓源码，解开就能跑 |
| `SHA256SUMS` | 上面几个的校验和 |

**便携版怎么来的**：`python -m build --outdir dist SpiritScout` 出 wheel，再
`powershell -ExecutionPolicy Bypass -File SpiritScout\launcher\build-portable.ps1`。
脚本下 python.org 的 embeddable 运行时、补 `._pth` 让 site-packages 生效、`get-pip.py` 装 pip
再 `--target` 装依赖，最后摆好 exe / `desktop.json` / 配置模板。细节见
[`docs/部署与配置.md`](SpiritScout/docs/部署与配置.md) 的「便携版」小节。

仓库里还留着更早那套「bat 启动」的便携包流程（`_work/build_release.py` →
`_work/validate_release.py` → `--zip-only`），它做的是没有 GUI 的老形态；要带窗口的桌面版就用上面这个。

装好后直接 `python -m spiritscout --port 8010`；注意 `--config` 与模型注册表按**当前工作目录**
解析，从仓库外安装时需要显式传 `--config` 指向你自己的 `system.yaml`。


## 安全边界

- 默认执行后端是 `host`：工作目录锁定、环境变量白名单、超时杀进程树，但**没有文件系统读隔离**。
- 管理员密码只保存 scrypt 加盐哈希（工作区 `admin.db`），明文不进命令行、不进日志；
  `admin.db` / `auth.key` 连同 `vault.*` 都在打包时被清掉，出厂包不含任何凭据。
- Web 控制台默认只绑 `127.0.0.1`；非回环绑定且未启用管理员认证时拒绝启动，
  判据见 [`SpiritScout/src/spiritscout/web/app.py:61`](SpiritScout/src/spiritscout/web/app.py#L61)。
- 只在你自己有授权的靶标上使用。完整条款见 [SpiritScout/SECURITY.md](SpiritScout/SECURITY.md)
  与上游 README 的「许可与使用约定」。

## 许可

Apache-2.0，版权归上游项目所有，见 [SpiritScout/LICENSE](SpiritScout/LICENSE)。
