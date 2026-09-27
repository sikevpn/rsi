# RSI MVP — 编排契约与阶段委派台账

> 依据：`RSI代理开发战略报告.md`（480 行，本仓库唯一非空 md）。
> 本文件是**老板层产物**：只做递归分解、委派、验收门记录，不含实现细节。
> 实现细节在各阶段交付物里，验收结果在文末台账（由真实命令产出，非人工填写）。

---

## 0. 编排前提（本轮实测，非推断）

| 事实 | 实测结果 | 对编排的影响 |
|---|---|---|
| 操作系统 | `Linux e2b.local 6.1.158+` | 文档假设的 Windows PowerShell 无法在此验收 |
| Python / Node | 3.11.2 / v22.22.3 | 选 Python 内核 |
| 执行后端 CLI | `claude`/`codex`/`opencode`/`gemini`/`hive`/`ralph` 全部 `NOT FOUND` | 必须做 adapter + 桩后端才能端到端验收 |
| LLM 凭证 | 仅 `GH_TOKEN`/`GITHUB_TOKEN`，无 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` | 真实模型调用在此不可执行 |
| 网络 | `pypi.org` 返回 `200` | 可装 dev 依赖 |
| 系统 Python 装包 | PEP 668 externally-managed，需 `--break-system-packages` | 运行时**零第三方依赖** |

### 委派的诚实声明

本会话**没有派生子代理的工具**（工具集内无 Task/Agent 类调用）。因此：

- 下表「委派对象」= 独立的阶段工作单元，由编排者按契约顺序执行，每阶段独立验收门把关；
- **交付物本身**实现了真正的委派：编排器通过子进程 spawn 执行者 / 审计者 / meta 角色三类代理（`rsi/backend.py` adapter 层），这符合文档 §5.2 ⑤→①→②→③→④ 的分层；
- 凡未能在本沙箱执行验证的项，一律在台账标注 `未验收` 及原因，不冒充通过。

---

## 1. 递归分解（WBS）

```
RSI MVP（文档 §6 第 0–4 阶段）
├── S0 环境与骨架 ────────────── 目标：可跑通的最小地基
│   ├── S0.1 Ralph 式文件黑板目录骨架（loop-project/）
│   ├── S0.2 gate.yaml / config schema 定稿
│   ├── S0.3 零依赖 YAML 子集解析器
│   └── S0.4 执行后端 adapter 层（Stub + 真实 CLI 子进程）
├── S1 外循环 ────────────────── 目标：无人值守把任务做完，不做任何自改
│   ├── S1.1 IMPLEMENTATION_PLAN.md 复选框解析/回写
│   ├── S1.2 单轮 fresh-context spawn
│   ├── S1.3 backpressure（独立跑 test/lint/typecheck）
│   ├── S1.4 护栏四件套：max-iterations / 连续失败 / thrashing / max-cost
│   ├── S1.5 kill switch（LOOP_PAUSED 文件标记）
│   └── S1.6 语义化退出码 0/1/2/3
├── S2 验证层 ────────────────── 目标：堵死「代理自报成功」
│   ├── S2.1 完成信号只认 DONE.json（不解析 stdout 自由文本）
│   ├── S2.2 编排器独立复跑对账（声明 vs 实测 exit code）
│   ├── S2.3 独立 Auditor（独立会话 + 只读 diff + 二值裁决 + 必须真跑 test）
│   └── S2.4 作弊注入红队（H4：拦截率 ≥80%）
├── S3 内循环自改 ────────────── 目标：基于 receipt 做最小一处自改
│   ├── S3.1 run receipt（SHA-256 钉住 + 终态枚举）
│   ├── S3.2 debrief 四因归因 + 反过拟合最小样本门
│   ├── S3.3 最小一处改动提案（diff ≤50 行，H5）
│   ├── S3.4 L1 report-only → proposals.md（不自动应用）
│   └── S3.5 快照 → 回归 → 保留/revert
└── S4 记忆 / 门禁 / 棘轮 / 自治
    ├── S4.1 memories.md 每轮自动注入（带字符上限）
    ├── S4.2 gate.yaml 机械强制（文件系统层拦截，H6：100%）
    ├── S4.3 golden task 回归套件（H1/H2 的度量衡）
    ├── S4.4 质量棘轮（只进不退，退步即 revert）
    └── S4.5 L1→L2→L3 自治阶梯
```

**依赖关系**：S0 → S1 → S2 → S3 → S4 严格串行（后一阶段的验收以前一阶段产物为前提）。
S2.4 / S4.2 是红队类，可与同阶段其它子项并行。

---

## 2. 阶段委派契约

| 阶段 | 委派对象（工作单元） | 输入 | 交付物 | 验收门（必须真实执行） |
|---|---|---|---|---|
| S0 | 骨架/配置/adapter 组 | 文档 §5.2、§6 第 0 阶段 | `loop-project/` 骨架、`rsi/miniyaml.py`、`rsi/gate.py`、`rsi/backend.py` | `AGENTS.md ≤60 行`；YAML 子集解析器单测全绿；adapter 能 spawn 子进程并回收 exit code |
| S1 | 外循环组 | S0 产物 | `rsi/blackboard.py`、`rsi/outer.py` | 桩后端跑通真实小任务；四类护栏各有一条失败注入测试；退出码语义正确 |
| S2 | 验证层组 | S1 产物 | `rsi/audit.py` + DONE.json 对账 | 10 次作弊注入，拦截率 ≥80%（文档 H4） |
| S3 | 内循环组 | S2 产物 | `rsi/receipts.py`、`rsi/inner.py` | receipt SHA-256 可复算；四因归因规则单测；单样本时**必须拒绝下结论** |
| S4 | 记忆/门禁/棘轮组 | S3 产物 | `rsi/regression.py`、gate 强制、自治阶梯 | 红队碰 `.env` 100% 被拦（H6）；棘轮对退化改动必 revert |

---

## 3. 验收台账

> 全部由 `bash` 真实执行产出。测试计数按文件单独跑出后相加，与全量 `163 passed` 对账一致。

| 阶段 | 验收命令 | 结果 | 状态 |
|---|---|---|---|
| S0 骨架/配置/adapter | `pytest tests/test_miniyaml.py tests/test_gate.py tests/test_backend.py -q` | **50 passed**（10+28+12）；`wc -l loop-project/AGENTS.md` → **59**（约束 ≤60）；`CliBackend` 用假 CLI 脚本真实 spawn，回收 `exit_code=7`、`tokens=42`、`cost=0.5` | ✅ |
| S1 外循环 | `pytest tests/test_blackboard.py tests/test_outer.py -q` | **19 passed**（6+13）；四类护栏各一条失败注入：`CONSECUTIVE_FAILURES` / `STALEMATE` / `ITERATION_LIMIT` / `BUDGET_EXHAUSTED`，加 `KILL_SWITCH`（预置 + 中途触发）与 `BACKEND_ERROR`；退出码 0/1/2/3 全部断言 | ✅ |
| S2 验证层 | `pytest tests/test_audit.py -q` | **20 passed**；H4 红队 10 次作弊注入**拦截 10/10 = 100%**（门槛 ≥80%）；含「删 2 条测试」与「全量 skip」两类会让套件假绿的作弊 | ✅ |
| S3 内循环 | `pytest tests/test_receipts.py tests/test_inner.py -q` | **38 passed**（11+27）；receipt SHA-256 可复算且篡改可检出；四因归因规则全覆盖；**2 条样本时拒绝下结论**并产出 0 个提案 | ✅ |
| S4 记忆/门禁/棘轮 | `pytest tests/test_regression.py tests/test_vcs.py tests/test_integration.py -q` | **36 passed**（23+7+6）；H6 红队 `.env`/`secrets/`/`rsi/`/`gate.yaml` **4/4 在文件系统层被拦**；棘轮三态 + 真实 `git revert` 回滚；端到端闭环打通 | ✅ |
| 全量 | `python3 -m pytest` | **163 passed in 18.65s** | ✅ |
| 基准套件 | `python3 -m rsi regress --suite golden/tasks` | 5/5 命中预期终态，`exit=0`，实测 **0.941s** | ✅ |
| CLI 体检 | `python3 -m rsi doctor` | `backend on PATH: none`；`gate allow: 4 pattern(s), deny 3 + 11 hardcoded`；`plan: 3 open / 3 total` | ✅ |

### 未验收项（不冒充通过）

| 项 | 原因 | 补验路径 |
|---|---|---|
| 真实 `claude`/`codex` 端到端 | 沙箱内四个候选 CLI 全部 `NOT FOUND`，且无 LLM API key | 在装有 CLI 的机器上跑 `python3 -m rsi run` |
| 报告 H1/H2/H3 实测数据 | 需真实模型跑 20/10/50 轮 | 度量框架已就位（`regression.py`），缺真实跑批 |
| Windows / PowerShell | 沙箱是 Linux；本实现选了跨平台 Python（报告 §5.2 原文即「PowerShell/Python」） | 在 Windows 上跑 `python -m rsi doctor` 与测试套件 |

