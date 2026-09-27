# rsi — 递归自我改进编程代理（MVP）

`RSI代理开发战略报告.md` 的可执行实现。报告的核心判断是：**11 个被调研的开源项目全部只做了
「外层任务循环」，没有一个实现「内层递归自我改进」**。这个仓库把自研精力集中在那块空白上，
外循环则做成薄胶水去外挂现成的 headless coding CLI。

## 两层架构（对应报告 §5.2）

```
⑤ 调度/入口     rsi/cli.py            doctor / run / meta / gate-check / receipts / regress
① 外循环执行    rsi/outer.py          fresh-context spawn → backpressure → 勾选 → 快照
② 验证层        rsi/audit.py          独立复跑对账 + 独立 Auditor + 净减少守卫
③ 内循环自改    rsi/inner.py          receipt → 四因归因 → 最小一处改动 → 门禁 → 回归 → 保留/回滚
④ 记忆/状态     loop-project/         IMPLEMENTATION_PLAN.md / memories.md / receipts/*.jsonl / gate.yaml
   度量衡       rsi/regression.py     golden task 套件 + 质量棘轮
   后端适配     rsi/backend.py        CliBackend（子进程）/ StubBackend（确定性验收）
```

## 快速开始

零第三方运行时依赖，Python ≥ 3.10。

```bash
python3 -m rsi doctor                      # 环境 / 配置 / 门禁 / 计划状态体检
python3 -m rsi run                         # 跑外循环（需要 PATH 上有 claude/codex 等）
python3 -m rsi meta                        # 跑内循环（读 receipt → 出自改提案）
python3 -m rsi gate-check memories.md      # 查某路径是否允许自改
python3 -m rsi gate-check .env             # 红队：应被拦（exit 1）
python3 -m rsi receipts --limit 10         # 看 run receipt 与 SHA-256 校验
python3 -m rsi regress --suite golden/tasks # 跑基准回归套件
```

开发依赖（仅测试需要）：

```bash
pip install pytest pyyaml        # pyyaml 只用于交叉校验内置 YAML 解析器
python3 -m pytest
```

## 关键设计约束（都在代码里强制，不靠提示词自觉）

| 报告要求 | 实现位置 | 机制 |
|---|---|---|
| 完成信号只认文件，不解析 stdout | `rsi/outer.py::_read_done` | 只读 `DONE.json`；每轮开始前清除上一轮残留 |
| 防自欺（假完成） | `rsi/outer.py` + `rsi/audit.py` | 编排器**独立复跑**测试，与 `DONE.json` 声明的 `test_exit_code` 对账，不一致记 `CLAIM_MISMATCH` |
| 防测试净减少 | `rsi/audit.py::count_tests` | 开跑前冻结收集数基线，审计时对比；另扫描 skip/xfail 注入 |
| 自改白/黑名单 | `rsi/gate.py` | `HARD_DENY` 硬编码在编排器里，改 `gate.yaml` 删不掉；精确 glob（`*` 不跨 `/`） |
| 最小一处改动（H5） | `rsi/gate.py::check(diff_lines=)` | diff > 50 行直接拒 |
| 反过拟合 | `rsi/inner.py::debrief` | 样本 < `min_samples_for_pattern` 时返回 `INSUFFICIENT_EVIDENCE` 且**不提任何改动** |
| 只进不退的质量棘轮 | `rsi/regression.py::ratchet_decide` | 退化 → `REVERT_REGRESSED`；改进要过 H2 门槛（完成率 +≥15% 或平均轮次 −≥10%） |
| 自治阶梯 L1→L2→L3 | `rsi/inner.py::can_auto_apply` | L1 永不自动应用，只写 `proposals.md` |
| 熔断四件套 + kill switch | `rsi/outer.py::_run_task` | max-iterations / 连续失败 / thrashing 签名重复 / max-cost / `LOOP_PAUSED` 文件 |
| 退出码语义化 | `rsi/outer.py` | 0 完成 / 1 失败 / 2 撞上限 / 3 外部停止 |

## 验证状态

`python3 -m pytest` → **163 passed**。覆盖外循环四类护栏注入、10 次作弊注入红队（报告 H4）、
门禁红队（H6）、四因归因、棘轮三态决策，以及一个完整的「外循环 → receipt → 内循环 →
记忆 → 下一轮外循环读到它」端到端闭环（`tests/test_integration.py`）。

`python3 -m rsi regress --suite golden/tasks` → 5/5 基准任务命中预期终态。

### 明确未验收的部分

- **真实模型调用**：本仓库开发环境里 `claude` / `codex` / `opencode` / `gemini` 均不在 PATH，
  也没有 LLM API key。`CliBackend` 的子进程路径用一个假 CLI 脚本做了真实 spawn + 退出码回收
  测试（`tests/test_backend.py::test_cli_backend_spawns_a_real_subprocess_and_recovers_exit_code`），
  但**没有对真实 claude CLI 跑过端到端**。
- **报告 H1/H2/H3** 需要真实模型跑 20/10/50 轮，此处只有度量框架，没有实测数据。
- **PowerShell**：报告写的是 Windows `loop.ps1`。本实现是跨平台 Python（报告 §5.2 本身写的是
  「~200 行 PowerShell/Python」），Windows 上可直接跑，但**没有提供 `.ps1` 壳，也没在 Windows 上实测**。

## 目录

```
rsi/                 编排器源码（自身在 HARD_DENY 里，代理不许改）
loop-project/        Ralph 式项目骨架：prompts/ AGENTS.md gate.yaml config/ memories.md ...
golden/tasks/        基准任务集（JSON），棘轮的度量衡
tests/               163 个测试
ORCHESTRATION.md     阶段分解与验收台账
```
