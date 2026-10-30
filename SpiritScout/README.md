<div align="center">

# 灵枢 · SpiritScout

**多智能体安全测试工作台**

在网页上下达任务，主 Agent 拆计划，子 Agent 并行执行，
过程、证据和产物都留在同一个会话里。

**简体中文 · [English](README_EN.md)**

[![Version](https://img.shields.io/badge/version-v0.23.0-2563eb?style=flat-square)](CHANGELOG.md) [![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square)](pyproject.toml) [![CI](https://github.com/FLIAZ/SpiritScout/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/FLIAZ/SpiritScout/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/license-Apache--2.0-16a34a?style=flat-square)](LICENSE)

[快速开始](#快速开始) · [三种模式](#三种模式) · [界面](#界面) · [工作原理](#工作原理) · [配置参考](#配置参考) · [常见问题](#常见问题) · [部署指南](docs/部署与配置.md)

</div>

> 仅用于已获授权的测试目标与赛事。任务范围的界定方式、审批策略与数据落点见 [数据与使用边界](#数据与使用边界) 与 [安全策略](SECURITY.md)。

## 它是什么

一个跑在本机或自建服务器上的安全测试工作台。你在网页上把任务说清楚——目标、规则、附件、模式——灵枢（主 Agent）把它拆成一张有依赖关系的任务图，交给专项子 Agent 并行推进，你在同一个页面里看进度、介入指导、验收产物。

它和"一个聊天框加一堆工具"的区别在四件事：

| | 意味着什么 |
| --- | --- |
| **有计划** | 任务是一张 DAG，不是一条消息接一条消息。哪条路线卡住、哪道题还没开始，图上看得见 |
| **有分工** | Web / Pwn / 逆向 / 密码 / Misc 各有子 Agent，各自带工具与知识，共享同一块黑板交换事实 |
| **有出处** | 每个结论都能追到具体那次工具调用和它的原始输出；拓扑区分真实产出与上下文延续 |
| **有人管** | SRC 的危险操作逐次问你；CTF 与竞赛预授权但全程留审计 |

模型不绑定：供应商、模型 ID、每个角色的指派都在控制台里配，改完即生效。
解题模板不写死在代码里——知识库存的是参考事实（平台特性、载荷、常见坑），步骤序列由模型结合现场决定。

## 三种模式

| 模式 | 典型场景 | 危险操作 | 无人值守 | 会向你提问 |
| --- | --- | --- | --- | --- |
| **SRC** | 授权资产分析、漏洞复测、渗透报告 | 删除文件、反弹 shell、上传 WebShell、容器逃逸、爆破等逐次审批 | 否 | 会：范围不清、缺信息时问 |
| **CTF** | Web、Pwn、逆向、密码、Misc 解题 | 预授权，全程留审计 | 可 | 会：任务缺关键信息时问 |
| **智能体竞赛** | 平台托管、多题调度、完成回收 | 预授权，全程留审计 | 是 | 不会；也不使用公开网页搜索 |

模式由**你在前端选择**，后端不改判；选过之后记在本机，下次默认还是它。
项目里的历史资产不会自动变成本次测试的授权目标。

## 界面

控制台是一个单页应用。左侧只放五项主功能，其余收进「设置」：

| 视图 | 用来做什么 |
| --- | --- |
| **任务** | 选模式，填目标、规则、附件，下发任务；看当前会话卡片 |
| **仪表盘** | 跨会话的调用量、Token、费用估算、异常告警（模型等待过久、有空闲名额却没派活等） |
| **编队** | 给灵枢和各子 Agent 分配模型与提示词 |
| **项目** | 把资产和会话归到一起；候选漏洞由「鉴真」独立复测 |
| **经验** | 沉淀下来的、可复用的判断与踩坑记录 |

会话详情不进导航，从任务列表点进去就是。

任务下发后就一直在跑，不因为你切了视图而停。**所以切走的时候左下角会浮出一条「N 个任务在后台运行」**——点开能看见每条的标题和状态（排队中 / 运行中），点一行直接切回去；全部收尾后坞自己消失。只报状态不报进度条：别的会话跑到第几步前端并不知道，与其画个假的，不如点进去看真的。

点侧栏底部的「设置」打开独立设置界面：左侧一列分类，右侧对应内容，不是弹窗；和主界面来回切不丢状态，入口还会记着上次看的那一页。

| 设置分类 | 用来做什么 |
| --- | --- |
| **模型** | 供应商地址、API Key、模型 ID、连通性测试、启用 / 停用 |
| **MCP 接入** | MCP 服务器配置、管理对话、Exa 检索 |
| **Skill 知识** | 技能包与参考知识 |
| **关于** | 版本、主题切换、退出登录 |

会话内的页签：**题目** · **实况** · **事件** · **Flag** · **拓扑** · **漏洞** · **交付物** · **报告** · **解题思路**。
「解题思路」只在 CTF 模式出现——生成前先确认团队信息与题目分章，可以留空，填过的会记住。

## 能力

| 能力 | 可以做什么 |
| --- | --- |
| 编队协作 | 主 Agent 拆分任务，子 Agent 派生路线、共享线索，按角色分配模型 |
| 执行工作台 | 展开任务、路线与推进步骤，查看工具结果及带审计出处的过程拓扑 |
| 项目与产物 | 保存资产和会话；候选漏洞独立复测；生成报告或解题思路 |
| 解题思路（WP） | 按赛方模板成文：生成前确认团队信息与题目分章（可留空、下次带出），按方向分章、逐题写过程与获取 Flag，可下载 Markdown |
| 浏览器与工具 | 接入 MCP、Skill 与 shell/Python 沙箱；SRC 可复用登录态并人工处理验证码 |
| 本地模型 | 把本机推理端点（LM Studio / Ollama）接成 MCP 工具：看状态、列模型、单轮提问；不出网不计费，适合摘要改写这类廉价活 |
| 模型与用量 | 配置供应商、编队与模型，查看费用估算、Token、端点返回的输入缓存用量 |
| 经验沉淀 | 把验证过的判断写回经验库，后续同类任务可直接取用 |

----

历史跑分记录 · tsecbench（2026-10-23）

原记录使用 DeepSeek v4.1 Flash，供参考

<img width="1606" height="838" alt="tsecbench 历史跑分记录" src="https://github.com/user-attachments/assets/f5cea640-aa57-40d2-9d21-919960aadd64" />

## 快速开始

### Docker（推荐）

需要 **Linux 容器模式**和 **Docker Compose 2.20+**。Windows 用 Docker Desktop，Linux 用 Docker Engine；macOS / ARM64 的兼容待开发。

```bash
git clone https://github.com/FLIAZ/SpiritScout.git
cd SpiritScout
python deploy.py up
```

Windows 用 `py -3 deploy.py up`，Linux / macOS 用 `python3 deploy.py up`。
首次运行会创建 `.env`、生成随机管理员密码、构建镜像并等待服务健康。

| 入口 | 地址 |
| --- | --- |
| **控制台** | <http://127.0.0.1:10010>　用户名与密码见项目 `.env` |
| **SRC 浏览器** | `python deploy.py up --browser` 后访问 <http://127.0.0.1:10011>，凭据与控制台一致 |

| 命令 | 作用 |
| --- | --- |
| `python deploy.py status` | 看容器状态 |
| `python deploy.py logs` | 跟踪日志 |
| `python deploy.py down` | 停服，保留数据卷 |
| `python deploy.py doctor` | 自检部署环境 |
| `python deploy.py migrate` | 旧版挂载部署迁移到数据卷 |
| `python deploy.py up --no-build` | 用已构建镜像重启，不重新构建 |
| `python deploy.py up --project-name other` | 隔离另一套并行的容器、卷与网络 |

镜像自带 Chromium 与 bubblewrap。CTF 工具箱按需在 `.env` 设 `INSTALL_TOOLKIT=1` 后重建镜像。
默认使用镜像内源码与独立数据卷；从旧版挂载部署升级前先停服迁移，不要直接删数据卷。

<details>
<summary>改用 Docker Compose 手动部署</summary>

复制 `.env.example` 为 `.env`，设置管理员用户名和强密码，再启动：

```bash
docker compose up -d --build --wait
```

源码开发覆盖、管理员恢复、反向代理、数据迁移与备份见 [部署与配置](docs/部署与配置.md)。

</details>

### Linux / Windows 本地运行

<details>
<summary>展开本地安装步骤</summary>

需要 Python 3.11+。原生浏览器工具另需 Node.js 22+ 和 Chromium/Chrome，也可用 `SPIRITSCOUT_CHROME_EXECUTABLE` 指定路径。

**Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
sudo apt install bubblewrap   # Debian / Ubuntu；Fedora 用 sudo dnf install bubblewrap
./launch.sh
```

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.\launch.ps1
```

访问 <http://127.0.0.1:8000>，`Ctrl+C` 停止。改端口：`./launch.sh --port 10010` 或把参数传给 `launch.ps1`。
监听外部地址前必须先配置管理员凭据与 HTTPS。

终端窗口会先打出绑定地址，**等端口真能连上再说一句 `[就绪] 浏览器可以打开了`**——
首次启动要建库、预热模型，等多久说不准，所以不拿固定秒数猜。之后每 60 秒报一行
`[状态] 已运行 01:00 · 会话 2（运行中 0） · 内存 244 MB`，不开任务管理器也能知道它活着。

```
灵枢 Web 控制台: http://127.0.0.1:8010  (管理员登录已启用，并发上限 4，Ctrl+C 停止)

[就绪] 浏览器可以打开了: http://127.0.0.1:8010
       每 60 秒报一次状态；Ctrl+C 停止

[状态] 已运行 01:00 · 会话 2（运行中 0） · 内存 244 MB
```

shell / Python 沙箱需要 Linux + bubblewrap；Windows 与 macOS 原生控制台降级为 host 后端，
拿不到这一整套隔离，需要完整工具链时请用 Docker。三者的虚拟环境不要混用。

</details>

### 跑通第一个任务

1. **配模型**：进「模型」页，填供应商地址、API Key 与模型 ID，点连通性测试。
   用不上的模型点「停用」即可退出选用，配置留着，想用再点回来。
2. **分角色**：进「编队」页，给灵枢和各子 Agent 指派模型（可以都指同一个）。
3. **下任务**：回首页选模式，填目标 / 题目、规则与附件，点「开始执行」。
4. **看现场**：进会话页，实况流看每一步，拓扑看推进结构，需要时在对话里补充信息。
5. **收产物**：交付物页取报告或解题思路，Markdown 可直接下载。

## 工作原理

![灵枢架构：任务调度、子 Agent 与共用模块](docs/images/architecture.svg)

```
用户任务 ──► 灵枢（主 Agent）
               │  规划：任务 DAG（题目 / 目标 → 可并行路线）
               ├──► 子 Agent 集群（Web / Pwn / 逆向 / 密码 / Misc …）
               │        └── 工具层：浏览器、shell/Python 沙箱、MCP、Skill
               │        └── 共享：黑板（事实）、尝试台账（防重复踩坑）
               └──► 汇总：Flag 判定、漏洞鉴真、报告 / 解题思路
```

- **规划在执行中调整**：主 Agent 看得到子 Agent 的进展与失败，会重排任务图，不是一次性计划。
- **事实集中在黑板**：线索、发现、拓扑写进同一处，子 Agent 之间不靠层层转述。
- **尝试台账防重复**：同一路线失败多次会被记录下来，换方法而不是反复撞同一堵墙。
- **Flag 由模型判定**：后端不做正则提取；提交结果与判定依据都留档。
- **模型网关统一处理**：供应商协议、流式输出、用量与缓存命中都在网关层收口。
- **工具层管权限**：按模式决定审批、沙箱与审计；步骤、观察、发现和产物都保留原始出处。

模块划分与关键函数索引见 [架构总览](docs/02-架构总览与项目结构.md) 与 [代码地图](docs/10-代码地图与关键函数索引.md)。

## 配置参考

### 配置文件

| 文件 | 内容 |
| --- | --- |
| `configs/system.yaml` | 系统配置：Web 监听、沙箱后端、事件总线、路径等（示例见 `system.example.yaml`） |
| `configs/models.yaml` | 供应商与模型清单（示例见 `models.example.yaml`） |
| `.env` | Docker 部署用的管理员凭据、镜像与可选工具箱开关 |

控制台里改的模型配置会覆盖启动时的快照，不需要重启。

### 环境变量

| 变量 | 作用 |
| --- | --- |
| `SPIRITSCOUT_ADMIN_USERNAME` / `SPIRITSCOUT_ADMIN_PASSWORD` | 管理员凭据，启动时导入管理员库（优先级最高） |
| `SPIRITSCOUT_SERVER_PASSWORD` | 旧版管理密码，仍兼容；用户名默认 `spiritscout` |
| `SPIRITSCOUT_VAULT_KEY` | 凭据库主密钥；不给则首次启动生成 `vault.key`（权限 0600） |
| `SPIRITSCOUT_REMOTE_LLM_KEY` | 远程模型 Key 的兜底来源 |
| `SPIRITSCOUT_SANDBOX_BACKEND` | `auto`（默认）/ `bwrap` / `host`。auto 有 bwrap 就用，Windows/macOS 退 host |
| `SPIRITSCOUT_HOST_BASH` | host 后端使用的 shell 路径（Windows 装 Git Bash 时用） |
| `SPIRITSCOUT_CHROME_EXECUTABLE` | 指定 Chromium/Chrome 可执行文件 |
| `SPIRITSCOUT_CHROME_CDP_URL` | 连接已有浏览器的 CDP 地址 |
| `SPIRITSCOUT_CHROME_MODE` | `cdp`（默认）或 `headless` |
| `SPIRITSCOUT_BROWSER_TMP_PRUNE_MB` | 浏览器临时档案的清理阈值，默认 64；写 `0` 表示每次退出都清 |
| `SPIRITSCOUT_BUS__BACKEND` | 事件总线后端，如 `redis` |
| `SPIRITSCOUT_REDIS_URL` | Redis 连接串 |

任意配置项都能用 `SPIRITSCOUT_<段>__<字段>` 覆盖，例如
`SPIRITSCOUT_WEB__PORT=10010` 等价于改 `system.yaml` 里的 `web.port`。

### 数据落在哪里

原生运行在 `.spiritscout/`；Docker 落在配置卷、数据卷和可选的浏览器档案卷。

| 路径 | 内容 |
| --- | --- |
| `sessions/` | 每个会话的工作区：黑板、审计、Flag、报告、解题思路、截图 |
| `resources/` | 知识库与资源库 |
| `admin.db` | 管理员与登录会话 |
| `vault.db` / `vault.key` | 加密后的供应商 Key 与主密钥 |
| `usage.db` | 调用量与 Token 计量 |
| `experience.db` | 经验库 |
| `audit.jsonl` | 全局审计流水 |
| `preferences.json` | 界面偏好（当前就是上次选的模式） |
| `wp-profile.json` | 解题思路用的团队信息（创建后出现） |

备份时把 `.spiritscout/` 整个目录和 `.env` 一起带走；只备份数据库不备份 `vault.key`，恢复后 Key 解不开。

### 命令行

```bash
spiritscout --version            # 版本
spiritscout --host 0.0.0.0 --port 8000
spiritscout --config path/to/system.yaml
```

## 常见问题

**模型连通性显示正常，任务却立刻失败？**
连通性测试只要求模型回一句 `ok`，不覆盖完整的流式工具请求。项目固定了兼容的 LiteLLM / MCP 版本，
更新依赖后重新构建镜像，不要单独升级 LiteLLM。排查见 [模型调用与依赖兼容](docs/部署与配置.md#模型调用与依赖兼容)。

**Windows 上任务跑不起来？**
shell / Python 沙箱依赖 Linux 与 bubblewrap。Windows 原生控制台会自动降级到 host 后端，工具能力受限。
需要完整能力请用 Docker Desktop；或装 Git Bash 并用 `SPIRITSCOUT_HOST_BASH` 指定。

**端口被占用？**
Docker 部署改 `.env` 里的端口映射；本地运行用 `--port`。换端口后记得用新地址访问。

**想换成别的模型？**
「模型」页新增供应商与模型 ID，然后去「编队」页把角色重新指派。不需要改配置文件或重启。

**解题思路里团队信息是空的？**
信息页可以完全留空——留空处写「（待填写）」，不影响生成。填过一次后会自动带出；
清空再生成等于忘掉。题目分章不落盘：换了题目 id 就重新按题面自动判定。

**会话跑到一半卡住了？**
先看仪表盘告警——模型调用等待过久、有空闲名额却没派活都会单独报出来。
再进会话的实况流看最后一条工具结果；需要时直接在对话里给方向。

**数据怎么迁移？**
Docker 用 `python deploy.py migrate`；手工迁移时停服 → 拷 `.spiritscout/`（或数据卷）→ 在新环境启动。
跨机器迁移要保留 `vault.key` 与 `admin.db`，否则凭据与登录态都失效。

## 数据与使用边界

- **授权范围**：由模型结合你的原话、项目规则和后续答复在上下文中维护；后端不写死禁打清单，扩围会来问你。
- **审批策略**：SRC 危险操作逐次审批；CTF 与智能体竞赛预授权并留审计。沙箱是加固，不是目标范围的确定性阻断。
- **凭据**：API Key 加密存在工作区。不要公开真实 Cookie、HAR 或审计原文。
- **调用成本**：模型与付费搜索的费用由所接入服务收取；仪表盘是估算值，实际以供应商账单为准。
- **缓存与基线**：缓存命中量取自端点返回值；失败、取消、未知用量分别记录。对照方法见 [缓存优化与测试](docs/05-核心算法与技术实现.md#稳定前缀与测试修复0122)。

## 文档与贡献

当前代码版本 **v0.23.0**。版本唯一来源、递增规则与历史说明见 [版本管理](CONTRIBUTING.md#版本管理)。

| 我想了解 | 阅读入口 |
| --- | --- |
| 安装、模型、浏览器、迁移与备份 | [部署与配置](docs/部署与配置.md) |
| 架构、执行流程和代码位置 | [项目文档索引](docs/README.md) |
| 核心算法与技术实现 | [核心算法与技术实现](docs/05-核心算法与技术实现.md) |
| 修复问题或提交新功能 | [贡献指南](CONTRIBUTING.md) · [Agent 工作约定](AGENTS.md) |
| 版本变化与兼容修复 | [更新日志](CHANGELOG.md) |
| 私密报告项目自身漏洞 | [安全策略](SECURITY.md) |

## 许可与使用约定

项目代码采用 [Apache License 2.0](LICENSE)。引用的知识库、Skill 和外部工具遵循各自的许可证。

<details>
<summary>法律免责声明与使用合规须知</summary>

### 1. 工具定位

本项目（以下简称「本工具」）为网络安全学术研究、授权安全测试、企业内部风险自查用途的开源技术工具。

本工具所有功能仅面向拥有合法授权的测试场景，旨在提升网络安全防御能力、助力漏洞合规治理、推进安全技术学术研究。

### 2. 严格授权使用原则

所有使用者必须提前获得目标系统的书面合法授权。

严禁在无授权、越权、超范围情况下，对以下对象进行扫描、探测、渗透、数据获取、流量分析、自动化测试：

- 互联网公网任意未授权系统
- 金融、能源、政务、运营商、交通等关键信息基础设施
- 第三方企业、个人、公有云任意业务系统
- 任何法律法规禁止测试的信息系统

未授权测试即属于违法行为，使用者自行承担全部法律责任。

### 3. 禁止滥用条款

所有使用者承诺：

1. 不得利用本工具实施非法入侵、非法控制、数据窃取、流量攻击、漏洞滥用等违法犯罪行为；
2. 不得将本工具用于黑产、牟利、恶意破坏、未授权批量扫描、网络骚扰等场景；
3. 不得绕过、破解本工具内置的安全限制、黑白名单风控机制用于非法用途；
4. 不得用于危害国家网络安全、扰乱公共秩序、侵犯他人合法权益的活动。

### 4. 责任边界（核心免责）

1. 项目开源作者、维护团队、贡献者：仅提供公开的技术代码与学术实现，不参与、不知情、不协助任何第三方的非法使用行为，不对第三方滥用产生的任何后果承担刑事、行政、民事连带责任。
2. 本工具技术中立，合法合规用途明确，任何使用者的违法操作均为独立个人行为，与项目作者无关。

### 5. 强制合规义务

使用者使用本工具即默认表示：

- 已充分知晓《中华人民共和国网络安全法》
- 已充分知晓《中华人民共和国刑法》第285条、第286条相关规定
- 已具备合法网络安全测试资质或授权资质
- 自愿承担所有使用风险及法律后果

### 6. 违规处置机制

项目团队保留以下权利：

- 随时关停仓库、终止分发、更新风控限制
- 举报、记录、留存恶意滥用行为证据
- 拒绝为非法使用者提供任何技术答疑、指导、更新、协助

### 7. 最终声明

本工具严禁非法滥用。任何违法使用行为，由行为人独立承担全部法律责任，与项目开发、维护、贡献团队无关。

</details>

## 致谢

<details>
<summary>知识库、参考项目、MCP、SKILL 源及用户</summary>

### 知识库数据来源

- [PayloadsAllTheThings](https://github.com/swisskyrepo/PayloadsAllTheThings)（MIT）
- [NoorQureshi/security-skills](https://github.com/NoorQureshi/security-skills)（MIT）

### 参考项目

- [carlospolop/HackTricks](https://github.com/carlospolop/HackTricks)（CC BY-NC-SA）
- [OWASP WSTG](https://github.com/OWASP/wstg)（CC BY-SA-4.0）
- [GTFOBins](https://github.com/GTFOBins/GTFOBins.github.io)（GPL-3.0）
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)（MIT）

### 项目使用的 MCP 服务器

项目配置和示例涉及以下 MCP 服务器，是否启用以本机配置为准：

| MCP | 许可 | 用途 |
| --- | --- | --- |
| [ida-pro-mcp](https://github.com/mrexodia/ida-pro-mcp) | 自定义 | 逆向：反编译 / 交叉引用 / 函数与类型检索（无头 idalib） |
| [yakit](https://github.com/yaklang/yakit) | 自定义 | Web 渗透：编解码 / HTTP 流量 / 模糊测试 / 指纹 / 端口 / 反序列化 |
| [playwright-mcp](https://github.com/microsoft/playwright-mcp) | Apache-2.0 | 浏览器自动化：JS 渲染 DOM / 点击 / 表单 / 截图 |
| pentester-mcp | 自定义 | 渗透工具集：nmap / nuclei / sqlmap / ffuf / impacket / hydra |
| burp-mcp | 自定义 | Web 漏洞扫描与模糊测试（PortSwigger 官方扩展） |
| shodan-mcp | MIT | 资产情报（出网至第三方服务） |
| virustotal-mcp | MIT | 文件 / 域名情报（VirusTotal 官方托管端点） |

### SKILL 源

- [obra/superpowers](https://github.com/obra/superpowers)
- [anthropics/skills](https://github.com/anthropics/skills)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)

### 用户

- [@BProbie](https://github.com/BProbie)：修正文档格式
- [@k1ne](https://github.com/k1ne7)：多平台兼容功能
- [@neko](https://github.com/neko-11451)：对登录页的前端美化

</details>

## Star History

<a href="https://www.star-history.com/?repos=fliaz%2Fspiritscout&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=fliaz/spiritscout&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=fliaz/spiritscout&type=date&theme=light&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=fliaz/spiritscout&type=date&legend=top-left" />
 </picture>
</a>
