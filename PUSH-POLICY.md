# 推送规则：什么进仓库，什么只留本机

> 这份文件是给人看的清单，`.gitignore` 是给 git 看的同一套规则。两边冲突时以 **不推** 为准——
> 漏推可以补，误推收不回来。最后更新：2026-11-13。

## 一句话原则

**源码、测试、文档、配置模板 → 推。运行数据、密钥、构建产物、本机私用脚本 → 不推。**

判断标准不是「这文件重要吗」，而是「别人 clone 下来会不会因此**多一份状态、少一份安全**」：
- 多一份状态：会话历史、模型清单、缓存、构建产物——别人拿到是噪音，还会让 `git status` 变脏；
- 少一份安全：flag、API key、控制台密码、vault 密钥——推上去就再也删不干净。

## 要推的

| 类别 | 例子 | 说明 |
|---|---|---|
| 源码 | `SpiritScout/src/**/*.py` | 主程序 |
| 前端 | `SpiritScout/src/spiritscout/web/static/**` | HTML/CSS/JS，无构建步骤 |
| 测试 | `SpiritScout/tests/test_*.py`、`test_*.js` | 行为契约，必须跟源码一起走 |
| 文档 | `README.md`、`README_EN.md`、`SpiritScout/docs/**`、`CHANGELOG.md` | 含实测经验与能力边界 |
| 配置**模板** | `configs/models.example.yaml`、`models.mock.yaml`、`system.example.yaml` | 带注释的最小可用模板 |
| 配置**本体** | `configs/system.yaml`、`configs/skills.yaml` | 已脱敏且跑通过，clone 下来直接能起 |
| 启动器与部署 | `start-local.ps1`、`启动服务.cmd`、`deploy-spiritscout.ps1` | 别人复现的入口 |
| 知识库种子 | `src/spiritscout/knowledge/data/security_skills.json` | 内置技能，属于产品内容 |
| 经验导出快照 | `experience-export/experience-insights.json` | 脱敏后的结论文本 |
| CI | `.github/workflows/**` | |
| 本文件 | `PUSH-POLICY.md` | 规则本身不敏感，公开出来省事 |

## 不推的

| 类别 | 具体条目 | 为什么不推 |
|---|---|---|
| **真实 flag** | 任何 `flag{...}` 里的赛题答案 | 公开仓库会污染题目；文档/测试里只能写 `flag{demo_value}` 这类占位符 |
| **密钥与凭据** | `.env`、`*.key`、`vault.key`、`admin.db`、`execution.key`、`cookies*.txt` | 推上去等于公开泄漏，且 git 历史洗不掉 |
| **本机模型清单** | `configs/models.yaml`、`configs/agent_models.yaml`、`configs/*.bak-*` | 含真实端点地址、密钥引用、模型选择；仓库只留 `.example` / `.mock` |
| **运行期状态** | `.spiritscout/`（会话、审计、经验库、用量、vault） | 私有数据；膨胀后单库到过 16 GB |
| **虚拟环境与工具** | `.venv/`、`.tools/` | 977 MB + 79 MB，用 `pyproject.toml` 重建即可 |
| **构建产物** | `dist/`、`dist-portable/`、`_build-out/`、`packages/`、`_stage/`、`*.exe`、`launcher/ui/shell.css` | 上百 MB，走 GitHub Release 分发 |
| **缓存** | `__pycache__/`、`*.py[cod]`、`.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/` | 纯噪音 |
| **测试临时目录** | `SpiritScout/tmp*/`、`spiritscout-tests-*/`、`pip-*/`、`.stale-*/` | Windows 上 `TemporaryDirectory` 清理常失败，一轮能留上千个 |
| **日志** | `*.log`、`runsrv.log`、`debug.log` | |
| **本机私用脚本** | `ensure_llm.ps1`、`start_range.ps1`、`stop_range.ps1`、`启动本地打靶系统.bat`、`停止打靶系统.bat`、`打靶系统-使用说明.md` | 另一个工作区写的本机一键启停；能用但不入库，内容已提炼进 README |
| **内部评估** | `评估报告.md`、`/audits/`、一批 `*_2026-*.md` 过程记录 | 含本地靶场真实 flag 或私有网关地址 |

## 推送节奏

**每次任务收尾就推一次**，不要攒着。理由不是洁癖：本地 `.spiritscout` 动辄几个 GB，
攒几轮之后「哪些改了」就说不清了，而这些数据本身又不进仓库，出问题时没有对照物。

推之前跑这三步（半分钟）：

```powershell
cd C:\Users\admin\Desktop\全自动打靶
git status --short                      # 1. 看有没有意外文件混进来
git diff --cached --stat                # 2. 看改动规模对不对得上这轮干的活
git add -A --dry-run | Select-String 'flag\{|api[_-]?key|sk-[A-Za-z0-9]{20}'
                                        # 3. 红线扫描：flag / 密钥
```

第 3 步命中就停下来逐个看：`flag{example_flag_here}`、`flag{a}`、`flag{demo_value}`
这类占位符没问题，**真实赛题答案必须换掉**。

## 推送

```powershell
git add -A
git commit -m "一行人话摘要（做了什么，为什么）"
git push origin main
```

提交信息按 `AGENTS.md`：一行说人话，别写 `update`、`fix bug`。

推完验证一句：

```powershell
git rev-parse HEAD; (git ls-remote origin main) -split '\s+' | Select-Object -First 1
```

两个哈希一致才算推送成功。`git push` 把进度写到 stderr，PowerShell 会报
`exit code 1`——**那是正常输出，不是失败**，以哈希比对为准。

## 已知的本机情况

- 校园网对 GitHub 不稳：`curl https://github.com` 可能返回 `000`，但 `git push` 往往仍能通
  （走的是不同的解析与端口）。推送失败时先重试一次，再考虑换网络。
- 本仓库的 git 根是 `全自动打靶\`，`SpiritScout\` 是子目录——**不要**在子目录里另建仓库。
- 顶层有 `.gitignore` 与 `SpiritScout/.gitignore` 两层，两份都生效，改规则时两处都要看。
