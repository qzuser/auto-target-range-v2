# 运行期经验沉淀（脱敏导出）

灵枢在真实会话结束后自行提炼的方法论条目。这里是**已脱敏的只读快照**，不是运行库本身。

## 文件

`experience-insights.json` —— 113 条可复用的解题洞察，每条含 `insight` 结论、`context` 适用场景、`tags` 标签、`source_model`、`captured_at`。

## 来源

`SpiritScout/.spiritscout/experience.db` 的 `insights` 表。该表由
`SpiritScout/src/spiritscout/knowledge/experience.py` 在会话收尾时写入
（洞察上限 600 字、场景上限 300 字）。

这个目录属于本机运行期状态，在 `.gitignore` 里，本文件是唯一被提交的版本。

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

## 重新导入

写回位置由 `SpiritScout/configs/system.yaml:65-68` 的 `experience` 段决定：
`experience.root` 留空时经验库跟随当前工作区（`<工作区>/experience.db`），Web 控制台则
指向共享目录。会话开工按 `recall_limit`（默认 6 条）召回注入提示词。

本快照仅用于留档与人工检索，不会被运行时自动读取；要生效需按上表字段写回 `insights` 表。
