# 0.24.3 — 首次启动自己设管理员密码，出厂包不带任何凭据

一次以「凭据」为主轴的修订：管理员密码从「文档教你 set 环境变量」变成「第一次启动
当场输两遍」，包里一个凭据文件都不带，顺手修掉两个一直在红的测试和一处把字节码
打进发布包的构建缺陷。

## 本次发版：0.24.2 → 0.24.3

### 主要变化

**1. 首次启动自己设密码，明文哪里都不落**

新增 `python -m spiritscout --set-admin-password`：

```bash
python -m spiritscout --set-admin-password          # 交互：输两遍，不回显
python -m spiritscout --set-admin-password --admin-username ops
python -m spiritscout --set-admin-password --if-missing      # 已有账号就跳过
python -m spiritscout --set-admin-password --password-stdin   # 自动化
```

- 只把 scrypt 加盐哈希写进工作区 `admin.db`；明文不进命令行（不会出现在进程列表）、
  不写日志、不落盘。
- 便携包 `1-启动服务.bat`、仓库 `start-local.ps1`、产品自带 `launch.ps1` / `launch.sh`
  现在都在起服务前跑这一步：还没有管理员才问，已有账号直接跳过。
- 不是交互终端（脚本、CI、管道）自动跳过，**不会卡住启动**；回车两次等于「不设密码」，
  控制台就只绑 `127.0.0.1`。
- 密码最短 8 位，用户名不许带 `:`、控制字符或超长。

**2. 出厂包里没有任何凭据**

`build_release.py` 组装时清掉 `admin.db` / `auth.key` / `vault.db` / `vault.key`，
`make_zip()` 之前再断言一次 `data\` 里没有它们，命中就删掉并中止出包。用户设的密码
属于他本机，不可能也不该随包分发——所以「包里带了个默认密码」这种事不会发生。

**3. 管理员库的只读检查不再顺手建库**

`AdminStore.has_admins()` / `_hash_for()` 改成库不存在直接返回、存在则 `mode=ro` 连接。
以前一个陌生请求戳一下登录接口，就能在「还没设密码」的机器上留一个空 `admin.db`，
让「首次启动」的判断失真。`upsert()` 现在内置凭据校验，格式约束收口到唯一写入口。

**4. `.env` 盖掉本地密码会留一行告警**

环境变量凭据优先是部署约定（Docker 一键脚本写 `.env` 就靠它），但它会悄悄替换使用者
首次启动设的那份密码。现在覆盖时打一条 WARNING 点名，并提示 `SPIRITSCOUT_ADMIN_SYNC=0`
可关闭。

**5. 构建与测试的修补**

- 验包起控制台时带 `PYTHONDONTWRITEBYTECODE=1`，清场阶段删 `app\**\__pycache__`，
  出包前再剪一遍——此前验包会在 `app\src\` 写回 112 个 `.pyc`，被 `--zip-only`
  一起打进发布包。
- 生成的 bat 里曾有一个 `\a` 被 Python 当成转义（`data\workspace\admin.db` 变成
  BEL + `dmin.db`）。现在写脚本/说明时统一断言「除 CR/LF/TAB 外不许有控制字符」，
  宁可构建失败也不发带隐藏字节的包。
- `test_host_guard.test_hardening_drops_inherited_aces` 修掉一条一直红着的断言：
  `Mandatory Label\Low Mandatory Level:(I)(NW)` 是系统完整性标签，`icacls
  /inheritance:r` 不动它，而且必须留着才撑得住「证据目录只读」。
- `_work/publish_release.py` 的 tag、notes 文件名与三个资产名全部从 `__version__`
  推导，发新版本不用改脚本。

**6. 文档**

根 `README.md` 的版本与产物清单回到实际（此前还停在 0.23.1 与 0.23.1 的三个资产名）；
便携包 `使用说明.txt` 重写「三步开始」并新增「管理员密码」章；`docs/部署与配置.md`
换成「首次启动设密码 / 手动改 / 忘了怎么办 / `.env` 优先级」；`docs/打包与产物说明.md`
补出厂不含凭据、`data\workspace\admin.db` 与 `auth.key` 的运行期结构，文件数与 zip
条目数改成重打后的实测值。完整逐条说明见仓库
[CHANGELOG](https://github.com/qzuser/auto-target-range-v2/blob/main/SpiritScout/CHANGELOG.md#0243---2026-11-01)。

### 从 0.24.2 升级

- 便携包：解压新包覆盖 `app\` `configs\` `runtime\` `1-启动服务.bat` `使用说明.txt`，
  **`data\` 整目录保留**（会话、经验库、`admin.db`、`vault.*` 都在里面）。哈希格式没变，
  已有 `admin.db` 会被跳过，不会让你重设密码。
- pip 安装：`pip install -U "spiritscout[toolkit] @ file:///…whl"`。
- Docker：`python deploy.py up --build`，`.env` 里的凭据照旧生效（并会覆盖本地那份，
  日志里有 WARNING）。

## 附件说明

| 文件 | 给谁 |
| --- | --- |
| `SpiritScout-0.24.3-portable.zip` | **最终用户**。64 位 Windows 解压即用，不需要装 Python |
| `spiritscout-0.24.3-py3-none-any.whl` | 已装 Python 的开发者 |
| `spiritscout-0.24.3.tar.gz` | 要审源码或从源码构建的人 |

便携包 `data\` 出厂只有 `说明.txt` 与预置的 `experience.db`（50 条做题经验），
没有任何 `admin.db` / `auth.key` / `vault.*`。装工具箱的 wheel 记得用 PEP 508 形式：

```bash
pip install "spiritscout[toolkit] @ file:///绝对路径/spiritscout-0.24.3-py3-none-any.whl"
```

写成 `xxx.whl[toolkit]` 会被 pip 静默丢弃 extras。

## 校验和

```
SHA256 (SpiritScout-0.24.3-portable.zip) = a069ddd1f273cd92fe8033d96e5227e48b585f4b1345b6880cdd30471eba812f
SHA256 (spiritscout-0.24.3-py3-none-any.whl) = be4103e0c23e3ba0f087af6ddc9abdbbd39057c1a6ee83321071eae42b5de26a
SHA256 (spiritscout-0.24.3.tar.gz) = 6c6b180a07a4f33a4e3fd3ccea15e1519bfdd5b7eb31b06577655e2ff3429717
```

Windows 核对：`Get-FileHash .\SpiritScout-0.24.3-portable.zip -Algorithm SHA256`。

## 验证情况

用包内解释器把便携包当「别人刚下载下来」跑了一遍（`_work/validate_release.py`，9 项全过）：

- 包内 `python.exe` 能导入全部依赖，版本号读到 0.24.3，`app\src` 优先于 site-packages；
- 沙箱解释器探测到 `runtime\Scripts\python.exe`，host 后端下 Python 工具可执行，
  `scripts\python.exe` 前缀/docstring 正常；
- `configs\system.yaml` 的五个路径键都落在 `data\`，包根不会误建 `.spiritscout`；
- 真起一次控制台，`GET /` 返回 200；
- `data\workspace` 下没有 `admin.db` / `auth.key` / `vault.*`；
- 用包内代码跑 `--set-admin-password`：退出码 0、`admin.db` 里只有 `scrypt$` 哈希、
  文件里搜不到明文、第二次调用是「跳过」。
- 后端 unittest 全量：Ran 1002 tests in 132.8s — OK (skipped=14)，0 失败 0 错误。
- `ruff check src/ tests/` 通过。

已知环境相关跳过：14 项，全部是本机能力缺失，不是失败：bwrap 命名空间遮蔽 5 项（Windows 走 host 后端，没有文件系统读隔离）、真实 Chrome / Playwright MCP 链路 4 项（需要另起 CDP 会话）、隔离 Redis 4 项（要 `SPIRITSCOUT_TEST_REDIS_URL` 或 `SPIRITSCOUT_TEST_DOCKER=1`）、非 Windows 的 ACL 用例 1 项。
