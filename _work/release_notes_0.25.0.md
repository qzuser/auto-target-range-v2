# 0.25.0 — 解出题、或者它在等你回答时，系统会弹你一下

一次以「别错过」为主轴的次版本：任务都在后台跑，解出一道题、或者灵枢卡在一个只有你能
回答的问题上，之前只有回到那一页才看得见。现在会弹系统通知——切到别的窗口也收得到，
点一下直接回到那个会话。没给通知权限也不会静默，退化成页面内提示加标签页标题计数。

## 本次发版：0.24.3 → 0.25.0

### 主要变化

**1. 新增 `GET /api/notifications`：此刻有什么值得叫醒你**

`web/notify.py` 把两个来源算成统一的条目，`web/routes/notify.py` 只做一层很薄的
暴露，鉴权仍由 `mount_auth` 的中间件统一收口：

| 类别 | 来源 | 口径 |
| --- | --- | --- |
| `solved` | 会话工作区 `flags.json` | **只有 `accepted is True` 才算解出**；未判定、判错都不算 |
| `question` | 会话内提问队列 `QuestionBroker.view()` | 与界面上的提问卡同源；进程内状态，重启即清空，不假装还在 |

- 条目 id 稳定（`flag:<会话>:<flag_id>` / `ask:<会话>:<qid>`），前端据此去重，重复拉取
  不会重复响。
- 附带 `counts`（各分类条数）和 `revision`（只由 id 集合决定）：客户端拿 revision 跟
  上次比，一样就直接跳过，省掉逐条比对。
- 读盘一律容错：文件缺失、半截 JSON、字段类型不对都当作没有这条。一条坏记录不会把
  整轮提醒打断，`flags.json` 按 mtime 缓存解析结果——几十个会话不必每轮重读磁盘。

**2. 前端 `notify.js`：只管弹，不管记**

- 浏览器给了通知权限就走系统通知（`new Notification(title, {body, tag: id})`）；点一下
  回前台并跳回那个会话。
- 没授权、或者浏览器不支持，就退化成页面内提示加标签页标题计数 `(3) 灵枢 · SpiritScout`
  ——**不静默**。最怕的是「以为它在提醒你」。
- 已读留在 `localStorage`，按 id 去重并封顶 400 条：多开几个标签页，各看各的屏；服务端
  不替谁记「已读」，也就不存在「一个标签页关掉、另一个也跟着安静了」。
- 正看着那个会话、而且页面在前台时不重复弹——屏幕上已经有提问卡或结果了。
- 开关关着时也不攒着：打开之后不会把历史条目一股脑补一遍。

**3. 挂进原有单一调度器，不另开定时器**

`polling.js` 的 `create()` 多一个可选的 `refreshNotify`，节奏是**可见 15 秒 / 隐藏 30 秒**
（比会话状态稀疏一档：提醒跨会话，不需要跟到秒级）。启动时先查一次，重开控制台不必干等
一轮。原来的列表/状态档位一字未动，`tests/test_polling.js` 补了提醒档位与停表断言。

**4. 设置里多一页「通知」**

权限状态（已允许 / 尚未授权 / 已被拒绝 / 不支持）、提醒开关、待提醒计数、发一条测试
通知、清空已读。通知权限只在点按钮这个用户动作里申请，不在页面加载时弹框。

**5. 验包加三件套探针**

`_work/validate_release.py` 起控制台后除了 `GET /`，再验 `/api/notifications` 的
返回结构、首页里的通知分类、`/static/js/notify.js` 的完整字节——出厂包少一件就等于
没这功能。（顺手把 `get()` 旁边补了 `get_all()`：只读前 2 KB 验不到首页靠后的设置面板。）

**6. 测试与顺手修掉的活儿**

- 新增 `tests/test_web_notify.py`（21 条）：只有 `accepted is True` 算解出、id 跨轮稳定、
  mtime 变了缓存失效、坏 JSON／坏队列／坏字段容错、排序与封顶、`revision` 只在 id 变化时
  变、路由契约，以及真实 `create_app` 下接口／首页／静态资源三件套和前端接线结构。
- 新增 `tests/test_notify.js`（9 组）：系统通知、重复拉取不重响、点通知跳会话、无权限退化、
  正看着不打扰、开关关着不攒、拉取失败静默、坏存储、已读封顶、测试通知按权限如实返回。
- `tests/test_usage_storage.py`、`test_web_auth.py`、`test_web_search.py` 里 4 处
  `with sqlite3.connect(...)` 改成 `closing(...)`：那个写法只提交不关句柄，Windows 上
  临时目录因此删不掉；本机 `%TEMP%` 不可用时，一轮全量会在仓库里留下二十几个 `tmp*`
  目录（实测 54 个）。
- `tests/test_benchmark_support.py` 起子进程时显式 `encoding='utf-8'`：中文输出遇上
  GBK 默认解码会抛 `UnicodeDecodeError`，红的是测试而不是代码。
- 新增 `MANIFEST.in`（`recursive-include tests *.js`）：setuptools 默认只收
  `tests/` 下的 `*.py`，0.24.3 及更早的源码分发包里只有前端源码、没有前端测试，
  从 sdist 构建的人跑不了 `node tests/test_*.js`——本次 sdist 里 25 个 JS 测试已齐全。

**7. 文档**

`README.md` / `README_EN.md` 的设置分类表加「通知」并说明提醒口径、退化行为与多标签页
取舍；`docs/02-架构总览与项目结构.md`、`docs/10-代码地图与关键函数索引.md` 补
`web/notify.py`、`web/routes/notify.py`、`web/static/js/notify.js` 与轮询档位。完整逐条
说明见仓库 [CHANGELOG](https://github.com/qzuser/auto-target-range-v2/blob/main/SpiritScout/CHANGELOG.md#0250---2026-11-01)。

### 从 0.24.3 升级

- 便携包：解压新包覆盖 `app\` `configs\` `runtime\` `1-启动服务.bat` `使用说明.txt`，
  **`data\` 整目录保留**（会话、经验库、`admin.db`、`vault.*` 都在里面）。
- pip 安装：`pip install -U "spiritscout[toolkit] @ file:///…whl"`。
- 通知权限是浏览器侧的事，第一次点「设置 → 通知 → 允许系统通知」才会问；不想收就关掉
  那一页的开关，功能照跑，只是不响。

## 附件说明

| 文件 | 给谁 |
| --- | --- |
| `SpiritScout-0.25.0-portable.zip` | **最终用户**。64 位 Windows 解压即用，不需要装 Python |
| `spiritscout-0.25.0-py3-none-any.whl` | 已装 Python 的开发者 |
| `spiritscout-0.25.0.tar.gz` | 要审源码或从源码构建的人 |

便携包 `data\` 出厂只有 `说明.txt` 与预置的 `experience.db`（50 条做题经验），
没有任何 `admin.db` / `auth.key` / `vault.*`。装工具箱的 wheel 记得用 PEP 508 形式：

```bash
pip install "spiritscout[toolkit] @ file:///绝对路径/spiritscout-0.25.0-py3-none-any.whl"
```

写成 `xxx.whl[toolkit]` 会被 pip 静默丢弃 extras。

## 校验和

```
SHA256 (SpiritScout-0.25.0-portable.zip) = 893ab84d9d92dc35929844657ed42dc745144c76cb9dff8778dfc61504d2d6c6
SHA256 (spiritscout-0.25.0-py3-none-any.whl) = 5c373d76d63da6a2b0931dab033955845a163db1295896c7e12f335602d9d43d
SHA256 (spiritscout-0.25.0.tar.gz) = 2cf4eb81db7f9a2384f475365b32584e3721bbc0230dae7eca7448507cf13e44
```

Windows 核对：`Get-FileHash .\SpiritScout-0.25.0-portable.zip -Algorithm SHA256`。

## 验证情况

用包内解释器把便携包当「别人刚下载下来」跑了一遍（`_work/validate_release.py`，9 项全过）：

- 包内 `python.exe` 能导入全部依赖，版本号读到 0.25.0，`app\src` 优先于 site-packages；
- 沙箱解释器探测到 `runtime\Scripts\python.exe`，host 后端下 Python 工具可执行；
- `configs\system.yaml` 的五个路径键都落在 `data\`，包根不会误建 `.spiritscout`；
- 真起一次控制台：`GET /` 200、`GET /api/notifications` 200（
  `{"items":[],"counts":{"solved":0,"question":0},"revision":"da39a3ee…"}`）、
  `GET /static/js/notify.js` 200 且内容完整；首页里能找到通知分类；
- `data\workspace` 下没有 `admin.db` / `auth.key` / `vault.*`；
- 用包内代码跑 `--set-admin-password`：退出码 0、`admin.db` 里只有 `scrypt$` 哈希、
  二次调用是「跳过」。
- 后端 unittest 全量：Ran 1023 tests in 146.5s — OK (skipped=14)，0 失败 0 错误。
- `ruff check src/ tests/` 通过；`node --check` 21 个前端文件全过；`node tests/test_*.js`
  25 个文件全过。

已知环境相关跳过：14 项，全部是本机能力缺失，不是失败：bwrap 命名空间遮蔽 5 项（Windows
走 host 后端，没有文件系统读隔离）、真实 Chrome / Playwright MCP 链路 4 项（需要另起 CDP
会话）、隔离 Redis 4 项（要 `SPIRITSCOUT_TEST_REDIS_URL` 或 `SPIRITSCOUT_TEST_DOCKER=1`）、
非 Windows 的 ACL 用例 1 项。
