# 运行期经验沉淀（脱敏导出）

灵枢在真实会话结束后自行提炼的方法论条目。这里是**已脱敏的只读快照**，不是运行库本身。

## 文件

`experience-insights.json` —— 可复用的解题洞察，每条含 `insight` 结论、`context` 适用场景、`tags` 标签、`source_model`、`captured_at`。
条数以文件里的 `total` 为准（每次提交都会刷新，别在这里写死数字）。

`legacy-state-0.12.9.json` —— 0.12.9 世代（2026-10-27~28）那份运行期状态根的**脱敏清点记录**：
只记条数、层级分布、时间范围、有多少条记录里出现过 flag 字面量，不落任何原文。
那份状态根本身（`blackboard.db` 11.9M + `usage.db` + `probe-audit.jsonl`）是早期以仓库根为
工作目录跑出来的游离数据——配置认的当前状态根是 `SpiritScout/.spiritscout`（启动器
`cwd = SpiritScout`），两边从来不是同一个落点。它已移出工作区，本文件是它留下的唯一痕迹。

## 每次提交自动带上

`git-hooks/pre-commit` 是本仓库的提交前钩子，做三件事：读运行库 → 与已提交的快照
合并 → 有变化就改写快照并 `git add` 进本次提交。也就是说「提交」和「带上最新经验」
是同一个动作，不需要记得手动导出。

```bash
python experience-export/install_hook.py            # 每个 clone 装一次（装/更新）
python experience-export/install_hook.py --check    # 只查：是否已装且与源文件一致
python experience-export/install_hook.py --uninstall
```

手动用同一个导出器：

```bash
python experience-export/export_experience.py             # 立刻同步一次
python experience-export/export_experience.py --check     # 只检查是否落后（落后退出码 1）
python experience-export/export_experience.py --self-test # 自检：脱敏幂等 + 聚合口径不变
```

行为约定：

- **只增不减**。库里有、快照也有的 id 按库里字段覆盖；库里没有的（0.12.9 / 0.23.x
  那批历史世代）原样保留——它们是早就提交过的沉淀，不能因为本机重建工作区就被抹掉；
  库里新增的按 `(captured_at, rowid)` 追加到末尾。
- **内容没变就不写文件**（`generated_at` 也不动），所以不会每次提交都刷一条空 diff；
  真长出新经验时才出现 diff，而那个 diff 就是本次提交的一部分。
- **运行库读不到就放行**：没跑过灵枢、或 db 正被控制台占用读不了时，钩子只往 stderr
  提示一句、保留上次快照，不会卡住提交。
- 要临时跳过：`git commit --no-verify`。
- 钩子与导出脚本在 [`.gitattributes`](../.gitattributes) 里固定为 LF——`core.autocrlf=true`
  的机器若把 `#!/bin/sh` 转成 CRLF，钩子会直接 bad interpreter 跑不起来。

## 来源

`SpiritScout/.spiritscout/experience.db` 的 `insights` 表。该表由
`SpiritScout/src/spiritscout/knowledge/experience.py` 在会话收尾时写入
（洞察上限 600 字、场景上限 300 字）。

这个目录属于本机运行期状态，在 `.gitignore` 里，所以运行库本身从不入库；被提交的只有
快照 `experience-insights.json` 和三个工具（`export_experience.py`、`install_hook.py`、
`git-hooks/pre-commit`）。

## 不含什么

- **不含任何靶场数据**：跑批过程摘要（轮次、flag 计数、停止原因）原本散在
  `local-range/work-*/` 的运行期目录里，已随本地靶场一并移除，未纳入本仓库。
- 不含 flag 值、目标地址、Cookie、会话密文、密钥库内容。

## 脱敏规则

导出时对每个字段依次做了替换，并在产物上跑了一遍反向校验（四类模式均零命中）：

- `http(s)://…` → `[目标地址已脱敏]`
- `IPv4(:端口)` → `[IP已脱敏]`
- flag 花括号形态的字面量 → `[flag值已脱敏]`
- `sk-` / `ghp_` / `xox[bap]-` 形态的密钥 → `[密钥已脱敏]`

实际结果：**113 条洞察原本就不含任何 URL、IP、flag 值或密钥**，正文全部是方法论叙述，
因此未发生任何替换；上面四条规则是导出管线的保险，不是对内容的修补记录。

## 与内置技能库的区别

- `SpiritScout/src/spiritscout/knowledge/data/security_skills.json`（660K）——
  **随代码发布的内置技能库**，是静态知识。
- 本目录——**运行后沉淀的经验**，随会话增长，属于数据而非代码。

## 重新导入（回灌）

写回位置由 `SpiritScout/configs/system.yaml` 的 `experience` 段决定：
`experience.root` 留空时经验库跟随当前工作区（`<工作区>/experience.db`），Web 控制台则
指向共享目录。会话开工按 `recall_limit`（默认 6 条）召回注入提示词。

运行时**不会**自动读这份快照，所以要让它生效得显式灌回去：

```bash
python experience-export/export_experience.py --import --dry-run   # 先看会新增多少条
python experience-export/export_experience.py --import             # 真写回 insights 表
```

什么时候需要它：换机器、重建 `.spiritscout`、或者库被清空过——那时快照里躺着一百多条，
而「经验库」页是空的，就是这个原因造成的。判重同时看 `insight_id` 与 `insight` 原文，
所以重复执行没有副作用；库里已有的条目不会被覆盖或删除（只增不减），
原始 `captured_at` 会转成 `ts` 保留，时间线不乱。

快照与运行库脱节时先跑一次 `--check`：它说 `[最新]` 就说明两边一致，说 `[过期]` 才需要同步。

## 从控制台提交 / 拉取（人人可提）

除了上面的 pre-commit 钩子，「经验」页右上角还有两个按钮走同一份快照：

- **提交**：把本地经验导成 `inbox/<提交人>-<UTC 时间戳>.json` 放进本目录，提交并推送。
  **每人一个文件**，不改 `experience-insights.json`，所以谁都能提、不用先拉最新、
  也不会顶掉别人的提交（没写权限就 fork 后推自己分支再提 PR）。
- **拉取**：`git fetch` 之后把主清单与 `inbox/` 下所有 `*.json` 一起读进来，按内容指纹
  只补本地缺的条目——本地已有的一律不覆盖、不删除。

手工往 `inbox/` 丢一个符合格式的 JSON 同样算一次提交，可以走网页或 PR。
格式见本目录 `experience-insights.json`（老清单格式）或
`SpiritScout/src/spiritscout/knowledge/sync.py` 的 `FORMAT = "spiritscout.experience/v1"`；
两种格式「拉取」都认。脱敏规则与钩子一致（URL / IP:端口 / 密钥 / flag 字面量一律替换）。