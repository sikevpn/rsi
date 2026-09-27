# RSI（递归自我改进）编程代理开发战略报告

> 整合分析基于 `explorations/` 目录下 11 份开源项目探索报告（01–11）。
> 分析视角：构建一个"会递归自我改进的编程代理"——不仅能在任务循环里写完代码，还能在跨次运行中改写自身的提示词、配置、工具链与流程，从而越跑越强。
> 报告日期：2026-09-28

---

## 一、执行摘要

### 1.1 RSI 编程代理的核心定义与目标

本报告所称 **RSI（Recursive Self-Improvement，递归自我改进）编程代理**，指这样一个系统：

- **外层**：给一个目标（spec / ticket / backlog），代理能在无人值守下持续执行、验证、重试，直到客观证据证明完成；
- **内层**：代理在跨次运行之间，**基于失败与成功证据，主动改写自身的系统提示词、任务模板、验证规则、配置、技能文件乃至源码**，并由客观回归信号判定"这次自改是否真的让下一次跑得更好"；
- **闭环**：自改 → 跑 → 度量 → 保留或回滚，形成一个**只进不退（quality ratchet）**的进化回路。

它区别于普通"AI 编码助手"的关键，不在于"能跑循环"，而在于**循环的对象包含代理自身**。

### 1.2 11 个项目探索的总体结论

读完 11 份报告后，最核心的发现是一句话：**整个开源生态把"外层任务循环"工程化得非常充分，但没有任何一个项目真正实现了"内层递归自我改进"。**

11 个项目全部定位为**编排层（orchestration layer）或方法论（playbook）**，它们本身不调模型、不含 agent 内核，而是把现成的 `claude` / `codex` / `opencode` / `gemini` CLI 当作"工人"包起来反复跑。在"自我改进"这条轴上，它们集体停留在三个层次：

1. **无自改进**（loop-engineering、ralphex）：循环只改目标仓库代码，改进对象永远是产品代码，不是代理自身；
2. **经验/记忆层自改进**（ralph-orchestrator 的 `memories.md`、hive 的 markdown 记忆 + SKILL.md 沉淀、LoopTroop 的失败笔记）：把踩坑写成 markdown，下一轮 prompt 里多读一段——**不写代码、不改配置逻辑**；
3. **提示词/配置层自改**（fractal 的 META 模式、loopy 的 debrief 最小一处改动、how-to-ralph-wiggum 的 `AGENTS.md` 回写）：meta 节点改写目标节点的 `NODE.md` / steps / scripts / prompts，**这是离 RSI 最近的一档，但仍被"目标必须停稳才能改"的门控住，且改的是配置不是源码**。

awesome 列表中真正触及"经审查的自我修改（reviewed self-modification）"的条目（Ouroboros、toryo 质量棘轮、hermes-agent 自动生成技能）只在目录里被点名，未被本批 11 个项目深入——这是下一阶段需要补查的空白。

第二个关键结论是**Windows 兼容性是硬约束**。11 个项目中：

- **不支持 Windows 原生**：ralph-orchestrator（依赖 Unix PTY/信号，需 WSL）、fractal（POSIX/tmux/bash 强绑定）；
- **Windows 未充分测试**：LongHorizon-Harness（supervisor 层用 `/proc`、`O_NOFOLLOW`）、ralphex（steer 功能 Windows 不可用）、how-to-ralph-wiggum（`loop.sh` 是 bash + envsubst）；
- **Windows 原生友好**：hive（自带 `hive.ps1` + `quickstart.ps1`）、LoopTroop（Scoop/Chocolatey/WinGet 分发）、loop-engineering（Node/TS）、loopy（纯 markdown skill，跨平台）。

这直接决定了"外挂哪些项目"的可选名单。

### 1.3 核心战略判断：哪些复用、哪些自研

| 决策 | 内容 | 依据 |
|---|---|---|
| **复用（命令行外挂）** | 外层循环的"零件"：fresh-context 重启、文件即记忆、backpressure 验证、僵局/死循环检测、worktree 隔离、退出码语义化 | [ralphex][ralph-orchestrator][how-to-ralph-wiggum][LongHorizon] |
| **复用（设计借鉴，不 fork）** | 三角色外循环骨架、事件驱动状态机、双 wiki 记忆、run receipt/debrief 元回路、L1→L2→L3 自治阶梯 | [LongHorizon][fractal][ralph-orchestrator][loopy][loop-engineering] |
| **自研（胶水层）** | 双层架构中的**内循环**——"度量本次运行 → 归因 → 最小改动自身 prompt/配置 → 回归验证 → 保留/回滚" | 11 个项目均未提供此闭环 |
| **自研（安全边界）** | 自改白名单/黑名单、kill switch、质量棘轮（只进不退）、自改前快照与一键回滚 | [fractal META][loopy][toryo 理念] |

**一句话战略**：站在 Ralph 生态的肩膀上做外循环（外挂现成 CLI 编排器），把全部自研精力集中在"内循环自我改进"这一层——这是 11 个项目共同留下的、也是 RSI 真正的价值空白。

---

## 二、11 个项目逐一分析表

| # | 项目 | GitHub | 核心定位 | 循环机制 | 技术栈 | Stars | 成熟度 | 可复用点 | 坑点 | RSI 相关度 |
|---|---|---|---|---|---|---|---|---|---|---|
| 01 | loop-engineering | [cobusgreyling/loop-engineering](https://github.com/cobusgreyling/loop-engineering) | 循环运维 playbook + CLI 脚手架 | L1→L2→L3 自治阶梯；maker/checker 对抗；STATE.md 状态脊柱 | Node/TS，17 个 npm 包 | 11.3k | 成熟模式库（v1.5.0，真实 dogfood） | gate.yaml 门禁、失败模式目录、worktree 隔离、预算/kill switch | 不做自修改；绑 GitHub Actions；状态是 markdown 弱机器可读 | **3/5** |
| 02 | LongHorizon-Harness | [AMAP-ML/LongHorizon-Harness](https://github.com/AMAP-ML/LongHorizon-Harness) | 长时程任务外循环外壳 | Manager→Executor→Auditor 三角色；fresh-context；验证检查点恢复 | Python ≥3.10，极轻依赖，子进程调外部 CLI | 1.6k | 早期（v0.1.7，8 周历史） | 三角色分离、独立 Auditor + 只读快照、失败分级、run 账本 | Windows 未充分测；POSIX supervisor；无 in-process 稳定 API；GUI 冗余 | **4/5** |
| 03 | LoopTroop | [looptroop-ai/LoopTroop](https://github.com/looptroop-ai/LoopTroop) | 本地工单→PR 编排器 | LLM 委员会 draft→vote→refine→coverage；Ralph 上下文清空重试；QA 失败回流 | TypeScript + Hono + XState + SQLite | 154（但 1351 commits） | early alpha，工程极严谨 | Ralph 重试、Bead 原子分解、委员会四步、SQLite 持久化 | 重人工门禁；不可嵌入；强绑 OpenCode；无跨运行自改进 | **3.5/5** |
| 04 | ralphex | [umputun/ralphex](https://github.com/umputun/ralphex) | Go 单二进制 Ralph 流水线 | 四阶段：执行→5 并行 review→跨模型评审→复审；max-iterations + patience 僵局检测 | Go，单二进制，子进程调 claude/codex | ~1.5k | 维护干净（553 commits，issue 极少） | 文件化状态游标、防死循环四件套、跨模型对抗评审、外置 prompt 模板 | 改进目标代码非自身；绑 claude/codex CLI 形态；Windows steer 不可用 | **3/5** |
| 05 | fractal | [plasma-ai/fractal](https://github.com/plasma-ai/fractal) | 仓库级递归多 agent 编排 | 五步状态机 PREPARE→PLAN→EXECUTE→REVIEW→COMMIT；worktree 树递归派生；**META 模式改其他节点 seed** | Python ≥3.12，tmux，plasma-wiki | 777 | 工程极强（2120 测试），但单人维护 | 五步循环、硬上限+预算收尾、META 自改模式、双 wiki、事件溯源 schema | POSIX/tmux 不可嵌入 Windows；全权 yolo 权限；自改停在配置层 | **4/5** |
| 06 | awesome-agent-orchestrators | [andyrewlee/awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators) | 200+ 编排工具目录 | 八大分类；Autonomous Loop Runners 类最相关 | 纯 markdown | — | 生态地图（Resting 区 2026-07 检查） | 选型导航；指出 Ouroboros/toryo/hermes 等自改进条目；对抗验证范式 | 一半是 GUI 多路复用器；不覆盖模型层自改进算法 | **4/5** |
| 07 | awesome-ralph | [snwfdhmp/awesome-ralph](https://github.com/snwfdhmp/awesome-ralph) | Ralph 生态资源导航 | 核心范式 `while :; do cat PROMPT.md \| claude; done`；文件即记忆；backpressure | 纯 markdown | — | 方法论目录 | 目录骨架、Vercel ralph-loop-agent SDK、挣扎检测/熔断/成本追踪条目 | 裸 while 无熔断；Agent 本身不改写自身；条目流动性大 | **4/5** |
| 08 | how-to-ralph-wiggum | [ghuntley/how-to-ralph-wiggum](https://github.com/ghuntley/how-to-ralph-wiggum) | Ralph 纯方法论指南 | 三阶段 JTBD→PLANNING→BUILDING；loop.sh + PROMPT_plan/build.md 模板 | 无代码，模板 markdown | ~1.8k fork | 文档完整但已停更 8 个月 | loop.sh、PROMPT 模板、AGENTS.md 模式、backpressure 设计、上下文工程经验值 | 无引擎；绑 Claude CLI；bash 脚本需 WSL；自改进仅 AGENTS.md 层 | **4.5/5** |
| 09 | loopy | [Forward-Future/loopy](https://github.com/Forward-Future/loopy) | 提示词方法论 + 可装 skill | 6 步 Observe→Choose→Act→Verify→Record→Repeat；run receipt→debrief 四因归因→最小一处改动 | JS（90% 是目录站 SaaS），skill 是纯 markdown | 3.2k | 概念热但生态小（19 条 loop） | run receipt schema、debrief 四因分类、反过拟合原则、终态枚举、Loop Doctor checklist | 无可执行引擎；人在环保守；记忆不跨会话自动演化 | **4/5** |
| 10 | ralph-orchestrator | [mikeyobrien/ralph-orchestrator](https://github.com/mikeyobrien/ralph-orchestrator) | Rust 薄编排层，事件驱动循环 | JSONL 事件文件驱动；Hat 角色订阅；完成信号只认 `ralph emit`；语义化刹车（Thrashing/Stale/成本上限） | Rust（tokio/clippy pedantic），npm 分发 | 3.2k | Beta 偏成熟（v2.10.1，538 commits） | 防自欺事件机制、TerminationReason 全集、假完成拒绝、退出码 0/1/2/3、MCP server | **不支持 Windows 原生**（需 WSL）；crates 不为嵌入设计；自改停在 memories.md | **4/5** |
| 11 | hive | [aden-hive/hive](https://github.com/aden-hive/hive) | 生产级多智能体 harness | "一个 loop 控制多个 loop"；AgentLoop 既是 Queen 也是 worker 克隆；judge reflexion；pilot→playbook 收敛 | Python 3.11+，LiteLLM，SQLite，**Windows PowerShell 原生** | 11k | 热度高但 backlog 巨大（925 open issues） | judge 三层管线反馈注入、n-gram 死循环检测、SKILL.md 自沉淀、park/resume、pointer 上下文治理 | 重应用轻库；自改进停在流程层非代码级；worker 禁止再派生 | **4/5** |

---

## 三、横向对比与模式提炼

### 3.1 循环架构模式分类

从 11 个项目中可提炼出 **6 种典型循环架构**：

#### 模式 A：Ralph 式 while 死循环（最朴素）
- **代表项目**：how-to-ralph-wiggum、awesome-ralph 里的裸 `while`、ralphex 的 Phase 1
- **机制**：外层 shell 不断重启无状态 CLI Agent，进度落盘到 `IMPLEMENTATION_PLAN.md` 复选框；每轮 fresh context
- **优点**：极简（一行 bash）、天然防腐烂、可解释、零额外依赖
- **缺点**：裸 while 无退出检测、无熔断、无成本上限，容易烧钱/原地打转 [awesome-ralph][how-to-ralph-wiggum]
- **适用场景**：MVP 起步、任务边界清晰、有现成测试套件做 backpressure

#### 模式 B：三角色外循环（Manager / Executor / Auditor）
- **代表项目**：LongHorizon-Harness
- **机制**：规划者只看状态和审计报告不看 trajectory；执行者全新上下文只做一个有界步骤；审计者只读快照 diff 证明"实际改了什么"，其报告是唯一可信中间状态
- **优点**：实现者永不自己打分；失败证据反哺下一轮；崩溃可从检查点恢复
- **缺点**：三角色各自一次 episode，token 成本高；Windows 未验证
- **适用场景**：长时程、需要可信"进步度量"的任务——**这正是 RSI 需要的反馈信号源**

#### 模式 C：五步状态机（PREPARE→PLAN→EXECUTE→REVIEW→COMMIT）
- **代表项目**：fractal
- **机制**：每轮固定 5 个 step，step 间独立进程；PREPARE 合并上游+整合子节点；REVIEW 要求"对记录在案的论断重新推导、重新跑验证"
- **优点**：纪律性强；硬上限体系（max-iters/depth/children/cost + 10% 预算收尾）成熟
- **缺点**：POSIX/tmux 绑定，Windows 不可跑
- **适用场景**：仓库级大任务、需要递归拆子任务

#### 模式 D：事件驱动循环（JSONL 文件即真相）
- **代表项目**：ralph-orchestrator
- **机制**：循环只从 `ralph emit <topic>` 写的 JSONL 文件读事件，不从 LLM 自由文本解析；Hat = 角色订阅表；`LOOP_COMPLETE` 必须 required_events 齐全 + 队列清空 + 人类 ack
- **优点**：**防自欺最强**（confabulation 在协议层被堵死）；退出码语义化（0/1/2/3）；LoopThrashing/LoopStale 空转检测精妙
- **缺点**：不支持 Windows 原生；文件布局强耦合 `.ralph/`
- **适用场景**：无人值守长跑、需要严格"假完成拒绝"

#### 模式 E：递归委派树（一个 loop 控制多个 loop）
- **代表项目**：fractal（worktree 树）、hive（Queen/worker 克隆）
- **机制**：节点在 PLAN 阶段自行判断是否派生子节点；分支命名即树结构（`<parent>.<name>`）；worker 被刻意做"窄"（hive：3 work + 1 grace + 禁止再派生）
- **优点**：任务树长到刚好适配问题；并行不互踩
- **缺点**：协调开销；fractal 全权 yolo 权限危险
- **适用场景**：可并行的大型任务分解

#### 模式 F：委员会对抗循环（多模型 draft→vote→refine）
- **代表项目**：LoopTroop、ralphex 的 5 并行 review agent
- **机制**：2–10 个模型独立起草 → 匿名结构化打分（固定 rubric、法定人数）→ 赢家综合落选稿 → 覆盖度补全
- **优点**：暴露单一模型盲区；跨模型评审信号强（claude 写、codex 评）
- **缺点**：token 成本高；适合规划/评审阶段，不适合高频内循环
- **适用场景**：RSI 中"自我改进方案"的评审环节——**改进者和评审者不应是同一个无差别的上下文** [ralphex]

### 3.2 自我改进机制谱系（从"无"到"代码级"）

把 11 个项目沿"自改深度"排开：

```
深度递增 →
─────────────────────────────────────────────────────────────►
[无自改进]  [经验/markdown 记忆]  [提示词/配置层自改]  [代码级自举]
   │              │                    │                  │
loop-engineering  ralph-orchestrator   fractal META       ← 空白
ralphex           memories.md          loopy debrief      （需自研）
                  hive markdown        how-to-ralph-
                  memory + SKILL.md    wiggum AGENTS.md
                  LoopTroop 失败笔记
```

| 层次 | 改什么 | 代表 | RSI 需要达到哪层 |
|---|---|---|---|
| L0 无自改进 | 只改目标代码 | loop-engineering、ralphex | 不够 |
| L1 经验沉淀 | 写 markdown 笔记，下轮 prompt 多读一段 | hive、ralph-orchestrator、LoopTroop | 起步层 |
| L2 提示词/配置自改 | meta 角色改写 seed/prompt/steps/scripts | fractal META、loopy 最小一处改动 | **MVP 目标层** |
| L3 工具/技能自造 | 自动生成 SKILL.md、新工具 | hive `writing-hive-skills`、hermes-agent | 中期目标 |
| L4 源码级自举 | 改写代理自身代码、架构 | 11 个项目**均未达到** | 远期目标，先不碰 |

**关键判断**：MVP 应瞄准 **L2（提示词/配置层自改）**，因为它是"改进收益/风险比"最优的一档——fractal META 和 loopy debrief 已经证明它可落地、可门控；L4 源码级自举在 11 个项目里无一成功先例，风险极高，应作为远期探索而非 MVP。

### 3.3 安全护栏模式汇总

| 风险类别 | 实现手法 | 来源项目 |
|---|---|---|
| **防死循环** | max-iterations 硬上限；review-patience=N 轮无 commit 判 stalemate；idle-timeout/session-timeout；LoopThrashing（同一放弃任务重复派发≥3次）；LoopStale（连续3次相同事件签名）；n-gram 相似度检测重复 tool call（DOOM_LOOP）；consecutive failures | [ralphex][ralph-orchestrator][hive] |
| **防自欺（假完成）** | 完成信号只认 JSONL 事件文件，不从自由文本解析；LOOP_COMPLETE 需 required_events 齐全+队列清空+人类 ack；独立 Auditor 只读快照 diff 证明实际改动；maker/checker 分离（实现者永不自己打分）；第二模型被要求"反驳已完成"；防测试净减少守卫 | [ralph-orchestrator][LongHorizon][loop-engineering][awesome 列表 no_human] |
| **防退化（只进不退）** | 质量棘轮（提交改进、回滚退化）；run receipt SHA-256 + 终态枚举；反过拟合（优化信号≠验收门，高影响产出独立验证）；测试棘轮 | [toryo(目录条目)][loopy][awesome 列表] |
| **成本控制** | max-cost 美元上限；每日 token 预算触发暂停；reserve_budget 默认 10% 只着陆不新建工程；先便宜 triage 有活才派重子代理；watchlist 空则早停；协调环节零 token（bernstein 思路） | [fractal][loop-engineering][ralphex] |
| **权限/爆炸半径** | gate.yaml 路径 denylist（.env/secrets/migrations/k8s）+ autoMerge allowlist + 单改 maxFiles:10；worktree 隔离失败即弃；Docker/一次性 VM 沙箱；worktree 只隔离分支不隔离 FS（README 自警） | [loop-engineering][fractal][how-to-ralph-wiggum] |
| **自治阶梯** | L1 report-only 跑一周 → L2 cautious → L3 unattended；verifier 连续对一周才放权；Loop Ready Score 权重偏向"最近真实跑过" | [loop-engineering] |

### 3.4 状态与记忆模式

| 模式 | 机制 | 代表 | 优劣 |
|---|---|---|---|
| **文件即记忆（markdown 黑板）** | 进度落 `IMPLEMENTATION_PLAN.md` 复选框 / STATE.md / AGENTS.md，每轮 fresh context 重读 | Ralph 系、loop-engineering、how-to-ralph-wiggum | 人可读、零基建；但机器弱、并发需锁 |
| **SQLite 事件溯源** | nodes/runs/iters/steps/events/signals/messages 全套表 + activity 时间线视图自动算 duration/cost | fractal、LoopTroop、hive tracker.db | 可回放、可统计、可恢复；schema 可直接借鉴 |
| **双 wiki 教义** | 私有 memory（只未来的自己用）vs 共享 wiki（别的节点复用），按受众路由，wikilink 指向唯一正本 | fractal | 多节点知识不重复；需额外 wiki CLI |
| **run receipt** | 不可变 loop 定义 SHA-256 + 验收条件 + 终态枚举 + 证据 + 动作 + 下一步 | loopy | 可追溯可复现；是"自改是否有效"的现成数据结构 |
| **JSONL 事件流** | 完成/进度只经 `ralph emit` 写文件；diagnostics 三件套（agent-output/orchestration/errors） | ralph-orchestrator | 防自欺；可离线重放 |
| **共享黑板 SQL** | 主代理 `tracker_query` 只读 SELECT 校验"还剩什么"永远是新鲜查询 | hive | 多 worker 协调天然 resume |

---

## 四、RSI 实现方向与路径假设（核心章节）

### 假设 1：双层架构——外循环（任务执行）与内循环（自我改进）分离

**主张**：RSI 代理应是两个嵌套循环，而非一个大循环。

```
┌─────────────────────────────────────────────────┐
│ 内循环（自我改进 meta-loop，低频，每 N 个外循环跑一次）│
│  run receipt → debrief 四因归因 → 最小一处自改     │
│  → 回归验证 → 保留 / 回滚                         │
└──────────────▲──────────────────────────────────┘
               │ 每次外循环产出 receipt 作为输入
┌──────────────┴──────────────────────────────────┐
│ 外循环（任务执行 loop，高频）                      │
│  目标 → fresh-context 执行 → backpressure 验证    │
│  → 检查点 → 直到完成/撞上限                        │
└─────────────────────────────────────────────────┘
```

**依据**：
- LongHorizon 证明外循环（plan→act→verify→recover）可独立工程化、可恢复 [LongHorizon]；
- loopy 的 run receipt→debrief→最小改动本身就是一个**元回路**，与外循环天然解耦 [loopy]；
- fractal 的 META 模式证明"meta 节点专门改目标节点 seed"是安全可落地的，但必须门控 [fractal]；
- 11 个项目的共同教训：把"任务执行"和"自我改进"混在一个上下文里会互相污染（Ralph 哲学：fresh context each iteration [awesome-ralph]）。

**为什么合理**：外循环追求"做完任务"，内循环追求"改进做任务的方式"。两者的频率、奖励信号、失败模式都不同——外循环高频、目标是任务完成；内循环低频、目标是指标提升。混在一起会导致代理在执行任务时分心去改自己，或在自我改进时被任务打断。

**如何验证**：先单独跑通外循环（阶段 1–2），再在其上叠加内循环（阶段 3）。若叠加后任务完成率不升反降，说明双层耦合失败，需加强隔离。

---

### 假设 2：自我改进的最小可行单元 = 改 prompt/配置，而非改代码

**主张**：MVP 的自改对象按风险从低到高排序，先做 L2，验证有效后再碰 L3，L4 留到最后。

| 优先级 | 自改对象 | 例子 | 风险 | 依据 |
|---|---|---|---|---|
| **MVP 第一步** | 改经验笔记/memory | 往 `memories.md` / `AGENTS.md` 追加一条"上次在 X 踩的坑" | 极低（纯追加，不改逻辑） | [hive][ralph-orchestrator][how-to-ralph-wiggum] |
| **MVP 第二步** | 改任务模板/prompt | meta 角色改写 `PROMPT_build.md` 里的护栏措辞、验收标准 | 低（文件级，可 git 回滚） | [fractal META][loopy debrief] |
| **中期** | 改验证规则/配置 | 调整 backpressure 命令、max-iterations、budget 参数 | 中（改错会导致验证失效） | [ralphex flags][fractal 硬上限] |
| **远期** | 自造新 SKILL.md/工具 | hive `writing-hive-skills` 模式 | 中高 | [hive][hermes-agent] |
| **暂不做** | 改代理自身源码/架构 | —— | 极高 | 11 个项目无成功先例，风险失控 |

**依据**：
- fractal META 明确把自改约束在"改 seed（prompt/step/scripts）"，且要求"目标必须停稳才能改"[fractal]；
- loopy debrief 强制"最小一处改动"，禁止大改——这是防发散的关键纪律 [loopy]；
- 所有项目中没有一个敢让代理改自身源码，说明业界共识是"配置层自改安全、代码层自改危险"。

**为什么合理**：RSI 的核心不是"改代码"，而是"让下一次跑比这一次好"。改 prompt/memory/配置就能达到 80% 的收益，且每一步都可 git diff、可回滚。代码级自举（L4）在没有充分护栏前是自杀行为。

**如何验证**：设计 A/B——同一批任务，分别用"改前 prompt"和"改后 prompt"各跑 5 次，测完成率/轮次/成本。若改后无统计显著提升，说明归因错误，回滚。

---

### 假设 3：用"测试棘轮 + receipt 回归"验证改进确实发生了

**主张**：自我改进最大的陷阱是"代理自我感觉良好"。必须有客观、独立、可复现的信号证明"这次自改真的更好了"。

三层验证：

1. **任务级 backpressure**（外循环）：test/lint/typecheck/build 失败即拒绝 [ralph-orchestrator][how-to-ralph-wiggum]；
2. **回归套件**（内循环）：维护一组固定的"基准任务集"（golden tasks），每次自改前后各跑一遍，对比完成率/平均轮次/token 成本；
3. **run receipt 对账**：每次运行产出 SHA-256 钉住的 receipt，debrief 时对比 receipt 指标，**禁止用同一证据既优化又验收**（反过拟合）[loopy]。

**依据**：
- loopy 把"优化信号 ≠ 验收门"写成硬规则，高影响产出必须独立验证 [loopy]；
- no_human 范式：第二模型在全新会话 review diff 并被要求"反驳已完成"，防测试净减少 [awesome 列表]；
- toryo 的"质量棘轮"：只接受提升指标的改进，退化立即回滚 [awesome 列表]；
- ralphex 的教训：claude 评估 codex 发现项时可能误判 false positive，patience/limit 只是兜底，没有"修复是否真改善指标"的客观闭环——这正是我们要补的 [ralphex]。

**如何验证**：先建 5–10 个 golden task（含已知难点），跑 10 次基线记录指标分布；之后每次自改都跑同一组，用均值对比决定保留/回滚。

---

### 假设 4：安全边界——自改白名单 + kill switch + 一键回滚

**主张**：代理能自改的范围必须是机器强制的白名单，而非 prompt 自觉。

| 边界 | 规则 | 来源 |
|---|---|---|
| **可自改目录**（白名单） | `prompts/*.md`、`memories.md`、`config/*.yaml`（参数级）、`skills/*.md` | 借鉴 fractal META 的"只改 seed" |
| **禁止碰目录**（黑名单，硬编码在编排器） | `.env*`、`secrets/`、`auth/`、`migrations/`、编排器自身源码、`gate.yaml` 本身、任何生产配置 | [loop-engineering gate.yaml] |
| **自改时机** | 只能在目标任务循环完全停止后改；运行中只能提提案给人 | [fractal META] |
| **kill switch** | 文件标记 `LOOP_PAUSED` / `loop-pause-all` 标签；max-cost 美元上限触发自动暂停；连续 N 次失败熔断 | [loop-engineering][ralphex][ralph-orchestrator] |
| **回滚** | 每次自改前 git commit 快照；回归不达标即 `git revert` | [fractal][ralphex] |
| **L1→L2→L3 放权** | 第一周强制 report-only（只提议自改、人批准）；连续正确一周后才允许自动应用低风险自改 | [loop-engineering] |

**依据**：loop-engineering 的 gate.yaml 证明"路径黑名单+单改文件数上限"必须由独立 CLI 机械强制，不能靠 prompt 自觉 [loop-engineering]；fractal 的全权 yolo 模式被 README 自己警告危险 [fractal]；how-to-ralph-wiggum 直言"不是会不会被攻破，而是什么时候被攻破，爆炸半径多大" [how-to-ralph-wiggum]。

**如何验证**：红队测试——故意让代理自改时碰黑名单路径，确认编排器在文件系统层拦截而非靠 prompt 忽略。

---

## 五、推荐整体架构

### 5.1 设计原则：能外挂就不整合

用户明确要求"能外挂就不整合"。因此架构原则是：**自研胶水层极薄，所有重活通过命令行子进程调用现成 CLI**，不 import 任何重型框架。

### 5.2 分层架构（文字描述）

```
┌─────────────────────────────────────────────────────────────┐
│ ⑤ 调度/入口层（自研，~200 行 PowerShell/Python）              │
│    loop.ps1：按阶段切 plan/build；读 receipts 决定何时触发     │
│    内循环；负责 kill switch、预算计数、退出码分发               │
└───────────────┬─────────────────────────────────────────────┘
                │ 子进程 spawn
┌───────────────▼─────────────────────────────────────────────┐
│ ① 外循环执行层（外挂现成 CLI）                                 │
│    Windows 首选：claude / codex CLI 无头模式                   │
│    （备选：hive CLI 原生支持 Windows PowerShell）              │
│    每轮 fresh context，状态靠文件黑板恢复                      │
└───────────────┬─────────────────────────────────────────────┘
                │ 产出
┌───────────────▼─────────────────────────────────────────────┐
│ ② 验证层（外挂 + 自研轻脚本）                                  │
│    - 客观：test/lint/typecheck（项目已有，命令写在 AGENTS.md）  │
│    - 独立 Auditor：另起一个 claude 会话，只读快照 diff 挑刺      │
│      （借鉴 LongHorizon Auditor + ralphex 跨模型评审）          │
└───────────────┬─────────────────────────────────────────────┘
                │ receipt（含指标）
┌───────────────▼─────────────────────────────────────────────┐
│ ③ 内循环自改层（自研，核心差异化）                              │
│    debrief 四因归因 → 最小一处改动提案 → 回归套件对比           │
│    → 通过则 git commit，不通过则 revert                       │
│    自改对象白名单：prompts/*.md、memories.md、config/*.yaml    │
└───────────────┬─────────────────────────────────────────────┘
                │ 读写
┌───────────────▼─────────────────────────────────────────────┐
│ ④ 记忆/状态层（纯文件 + SQLite，跨平台）                        │
│    - IMPLEMENTATION_PLAN.md（任务黑板，Ralph 模式）             │
│    - AGENTS.md（操作手册，≤60行）                              │
│    - memories.md（经验笔记，每轮注入）                          │
│    - receipts/*.jsonl（run receipt，SHA-256 钉住）             │
│    - gate.yaml（自改白/黑名单，独立 CLI 强制）                 │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 哪些组件直接复用（命令行外挂）

| 组件 | 用哪个项目 | 怎么外挂调用 |
|---|---|---|
| **执行后端** | `claude` / `codex` CLI 无头模式 | `claude -p --dangerously-skip-permissions --output-format stream-json`（how-to-ralph-wiggum 模板） |
| **外循环调度逻辑** | 借鉴 ralphex/LongHorizon，但**不自建重型编排器**（因 Windows 兼容问题） | 自己写 ~100 行 PowerShell 循环，调用上面 CLI；借鉴 ralphex 的 max-iterations/patience 参数思路 |
| **独立 Auditor** | 借鉴 LongHorizon Auditor + ralphex 跨模型评审 | 子进程再起一个 `claude` 会话，prompt 被指示"专挑拒绝理由、必须真跑 test 贴输出" |
| **记忆文件格式** | Ralph 系目录骨架 | 直接抄 `loop.sh` + `PROMPT_build.md` + `PROMPT_plan.md` + `AGENTS.md` + `IMPLEMENTATION_PLAN.md` [how-to-ralph-wiggum] |
| **run receipt 格式** | loopy receipt schema | 抄其字段定义（SHA-256、终态枚举、证据、动作、下一步），用 JSONL 落盘 |
| **防自欺机制** | ralph-orchestrator 的"事件只认文件" | 完成信号必须由代理写 `DONE.json`（含 test 输出）产生，编排器只认文件不解析 stdout 自由文本 |
| **Windows 备选 harness** | hive（原生 `hive.ps1`） | 若自研外循环不够用，`hive serve` 起 HTTP API 外挂调用 |

### 5.4 哪些部分必须自己写胶水代码

1. **内循环 debrief→自改→回归**：11 个项目均无此闭环，是核心自研；
2. **gate.yaml 强制执行器**：借鉴 loop-engineering 思想，但写成 Windows 原生脚本；
3. **golden task 回归套件**：RSI 的"度量衡"，必须自建；
4. **双层循环的触发逻辑**：每跑 N 个外循环任务才触发一次内循环（避免自改过频导致抖动）。

### 5.5 数据流与控制流

- **控制流**：`loop.ps1` 读 `IMPLEMENTATION_PLAN.md` → 挑第一个未完成项 → spawn `claude -p`（fresh context）→ 跑完跑 test → 成功则勾复选框+commit，失败则记 receipt → 循环；
- **数据流**：每轮结束写一条 `receipts/run-<ts>.jsonl`；每跑完 N 轮（或每撞一次上限）触发内循环：读最近 N 条 receipt → debrief 归因 → 提议改 `prompts/` 或 `memories.md` → 跑 golden task 回归 → 决定 commit/revert。

---

## 六、最小可行 RSI 循环（MVP）搭建步骤

### 第 0 阶段：环境与工具准备

**目标**：在 Windows 上把外挂 CLI 跑通。

- 安装 `claude` CLI（或 `codex` CLI），完成认证；
- 确认 `claude -p "hello" --output-format stream-json` 能在 PowerShell 里 headless 跑通；
- 建项目目录结构（直接抄 Ralph 骨架）：
  ```
  loop-project/
  ├── loop.ps1              # 外层循环（自研，~80 行）
  ├── PROMPT_build.md       # 构建模式指令
  ├── PROMPT_plan.md        # 规划模式指令
  ├── AGENTS.md             # 操作手册（≤60行，写清 build/test/lint 命令）
  ├── IMPLEMENTATION_PLAN.md
  ├── gate.yaml             # 自改白/黑名单
  ├── memories.md           # 经验笔记（空起步）
  ├── receipts/             # run receipt 目录
  └── specs/                # 需求规格
  ```
- 目标项目必须已有可跑的 `test` / `lint` 命令（backpressure 的前提）。

**验收标准**：`claude -p` headless 能在 PowerShell 里端到端跑通一个小任务并返回 exit code。
**预计工作量**：0.5 天。
**风险点**：claude/codex CLI 在 Windows 上的权限弹窗；`--dangerously-skip-permissions` 需确认 Windows 支持。

---

### 第 1 阶段：外循环跑通

**目标**：用最朴素的 Ralph while 循环把任务做完，不做任何自改。

- 写 `loop.ps1`：读 `PROMPT_build.md` → `Get-Content PROMPT_build.md | claude -p --dangerously-skip-permissions --output-format stream-json` → 跑完自动跑 test → test 过则 `git add -A; git commit` → 更新 `IMPLEMENTATION_PLAN.md` 复选框 → 下一轮；
- 加最小护栏：`max-iterations`（默认 50）、连续失败 3 次即停（借鉴 ralphex/ralph-orchestrator）；
- **不**用 ralph-orchestrator/fractal（Windows 不兼容）。

**验收标准**：给一个真实小需求（如"给 X 模块补 5 个单测"），代理能无人值守跑完，test 全过，git 历史干净。
**预计工作量**：1–2 天。
**风险点**：上下文腐烂（靠 fresh context 缓解）；test 基建缺失导致 backpressure 失效。

---

### 第 2 阶段：加验证层

**目标**：堵住"代理自报成功"的漏洞。

- 加 **独立 Auditor**：外循环每完成一个任务，另起一个 `claude` 会话，prompt 明确"你是挑错者，不信任执行者，必须真跑 test 并贴输出，专找拒绝理由"（借鉴 LongHorizon Auditor + loop-engineering maker/checker）；
- Auditor 意见二值化 pass/fail；fail 则打回重跑；
- 加 **完成信号只认文件**：代理必须写 `DONE.json`（含 test 退出码和输出），编排器只认这个文件，不解析 stdout（借鉴 ralph-orchestrator 防 confabulation）。

**验收标准**：人为注入一个"代理改了代码但 test 没真跑"的作弊场景，Auditor 能拦住。
**预计工作量**：1 天。
**风险点**：Auditor 成本翻倍；Auditor 自己也可能放水——需用不同模型或不同 prompt 模板。

---

### 第 3 阶段：加自改层（最小自改：改 prompt/memory）

**目标**：内循环第一次跑通——基于 receipt 做最小一处自改。

- 每轮外循环结束写一条 receipt（JSONL）：`{ts, task, iterations, tokens, test_pass, verdict, notes}`（抄 loopy receipt schema）；
- 每跑完 N=5 个任务触发一次内循环：
  1. 读最近 5 条 receipt；
  2. debrief 四因归因：loop 设计问题 / 执行选择问题 / 环境工具故障 / 目标不现实（抄 loopy）；
  3. 提出"能改变结果的最小一处改动"——**只改 `memories.md` 追加一条经验，或微调 `PROMPT_build.md` 措辞**；
  4. **L1 阶段：只写提案到 `proposals.md`，不自动应用**，人看一眼批准后才应用；
  5. 应用前 `git commit` 快照，应用后跑 golden task 对比，退步则 revert。

**验收标准**：内循环能产出至少一条合理的自改提案（如"memories.md 追加：这个项目的 test 命令是 `npm run test:unit` 不是 `npm test`"），且人批准后下一轮外循环确实读了它。
**预计工作量**：2–3 天。
**风险点**：从单条 receipt 归纳模式是过拟合（loopy 明确警告"单跑=一个数据点不构成模式"）——必须攒够样本再下结论。

---

### 第 4 阶段：加记忆与经验沉淀 + 自治升级

**目标**：从 L1（人批准）升到 L2（低风险自改自动应用）。

- 把 `memories.md` 做成每轮外循环自动注入的上下文（Ralph 模式）；
- 建 golden task 回归套件（5–10 个固定任务），每次自改前后跑；
- gate.yaml 机械强制自改白名单：脚本检查自改 diff 是否只碰 `prompts/`、`memories.md`、`config/`，碰黑名单即拒绝；
- 连续一周 Auditor 通过率 >90% 后，允许低风险自改（追加 memory）自动应用，高风险自改（改 prompt 逻辑）仍人批。

**验收标准**：连续跑一夜（8 小时）无人值守，无死循环、无成本失控、无碰黑名单；golden task 指标趋势向好。
**预计工作量**：2–3 天。
**风险点**：成本失控（必须 max-cost 美元上限）；自改发散（最小改动原则 + 回归棘轮兜底）。

---

## 七、风险与待验证假设

### 7.1 技术风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| **Windows 兼容性** | ralph-orchestrator/fractal/LongHorizon 三大最相关项目均不能 Windows 原生跑 | 不自建它们的编排器；用 PowerShell 自写薄循环；执行后端选 Windows 已验证的 claude CLI；备选 hive（原生 ps1） |
| **外部 CLI 依赖绑架** | claude/codex 一改计费/CLI 形态，ralphex 就被迫跟改（ralphex README 已被 2026-06-15 计费变更逼出一整章 wrapper） | 抽象 adapter 层，切换后端成本低；不把架构绑死在单一 CLI |
| **成本失控** | 多模型委员会 + 长重试循环烧 token（LoopTroop 教训） | max-cost 美元硬上限；reserve 10% 预算收尾；先便宜 triage 有活才派重子代理 |
| **test 基建缺失** | backpressure 依赖已有测试；没有 test 的项目 backpressure 退化为 LLM-as-judge | 早期只在有测试的目标项目上跑；无测试项目先补测试（这本身可作外循环任务） |
| **CLI 版本漂移** | how-to-ralph-wiggum 已停更 8 个月，Claude CLI flag 可能过时 | 以当前 `claude --help` 为准，不抄过时 flag |

### 7.2 安全风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| **自改导致退化** | 代理改了 prompt，结果越改越差 | 质量棘轮：golden task 回归退步即 git revert；L1 先人批 |
| **无限循环/烧钱** | Ralph 裸 while 无熔断 | max-iterations + patience 僵局检测 + consecutive failures + max-cost（抄 ralphex/ralph-orchestrator） |
| **权限越界** | 代理自改时碰到 secrets/migrations/源码 | gate.yaml 黑名单在文件系统层硬编码拦截，不靠 prompt 自觉 [loop-engineering] |
| **自欺/假完成** | 代理嘴上说做完实际没做 | 完成信号只认 `DONE.json` 文件 + test 真跑输出 [ralph-orchestrator] |
| **自反馈过拟合** | 用同一证据既优化又验收（loopy 警告） | 优化信号与验收门分离；高影响自改用独立 Auditor |
| **沙箱缺失** | yolo 模式绕过 CLI 权限系统 | 目标项目放一次性 VM/容器；最小密钥；限制网络 [how-to-ralph-wiggum] |

### 7.3 待验证关键假设列表

| # | 假设 | 验证实验 | 通过标准 |
|---|---|---|---|
| H1 | 双层架构（外循环+内循环）优于单循环 | 对比"有内循环"vs"无内循环"各跑 20 个 golden task | 有内循环组完成率显著更高、平均轮次更低 |
| H2 | 改 prompt/memory（L2）能带来可测提升 | A/B：改前 prompt vs 改后 prompt 各跑 10 次 | 完成率提升 ≥15% 或平均轮次下降 ≥10% |
| H3 | Windows 上 claude CLI headless 足够稳 | 第 0–1 阶段连续跑 50 轮无 CLI 层崩溃 | 崩溃率 <5% |
| H4 | 独立 Auditor 能有效拦假完成 | 注入 10 次故意作弊（改代码不跑 test） | Auditor 拦截率 ≥80% |
| H5 | 最小一处自改原则能防发散 | 观察内循环 50 次自改提案 | 无一次自改 diff 超过 50 行；无回归退化 |
| H6 | gate.yaml 黑名单能被机械强制 | 红队：指示代理碰 `.env` | 100% 在文件系统层被拦 |

---

## 八、结论与下一步行动

### 8.1 五条最关键结论

1. **11 个项目全部停留在"外层任务循环"，无一实现真正的内层递归自我改进。** 最接近的是 fractal META（配置层自改）和 loopy debrief（元回路），但都被门控、且不碰源码。RSI 的真正价值空白在"内循环"，这是自研主战场。
2. **外循环工程零件已经非常成熟，不需要自研。** fresh-context 重启、文件即记忆、backpressure、僵局检测、worktree 隔离、独立 Auditor、退出码语义化——这些在 ralphex/ralph-orchestrator/LongHorizon/Ralph 生态里都有现成答案，直接借设计、用 CLI 外挂即可。
3. **Windows 兼容性砍掉了一半候选。** ralph-orchestrator 和 fractal 这两个最强编排器都不能 Windows 原生跑；hive 是少数 Windows 原生的生产级 harness。因此外循环调度应自己写薄 PowerShell 胶水，而非 fork 重型编排器。
4. **MVP 的自改对象应严格限制在 prompt/memory/配置层（L2），不碰源码（L4）。** 这是 11 个项目共同的安全共识——fractal META、loopy 最小改动、loop-engineering gate.yaml 都指向同一结论：配置层自改收益高、可回滚、风险可控。
5. **防自欺是 RSI 的生死线。** ralph-orchestrator 的"完成信号只认 JSONL 文件"、LongHorizon 的独立 Auditor、loopy 的反过拟合原则三者结合，才能堵住"代理自我感觉良好但实际没改进"这个 RSI 最致命的失败模式。

### 8.2 立即可以开始的三个行动项

1. **今天**：在 Windows 上验证 `claude -p --dangerously-skip-permissions --output-format stream-json` 在 PowerShell 里 headless 跑通一个真实小任务，确认 exit code 和 stdout 可解析。这是整个 MVP 的地基。
2. **本周**：抄 Ralph 目录骨架（loop.ps1 + PROMPT_build/plan.md + AGENTS.md + IMPLEMENTATION_PLAN.md），在一个已有测试套件的目标仓库上跑通第 1 阶段外循环，记录第一次 run receipt。
3. **本周内**：精读 fractal 的 `_node/modes/META.md` 和 loopy 的 `references/debrief.md` 两个文件，把"内循环 debrief→最小自改→回归"的 prompt 模板写出来——这是自研内循环的蓝本。

---

*本报告基于 `explorations/01` 至 `11` 共 11 份探索报告综合提炼。所有关键论断均以 [项目名] 标注来源。*
