# AGENTS.md — 操作手册（≤60 行，硬性约束）

你是本仓库的执行代理。每轮都是**全新上下文**，先读本文件与 `IMPLEMENTATION_PLAN.md`。

## 1. 你要做什么

1. 打开 `IMPLEMENTATION_PLAN.md`，取**第一个未勾选**的 `- [ ]` 任务。
2. 只做这一个任务。不要顺手改别的。
3. 做完后勾选该复选框为 `- [x]`。
4. 写 `DONE.json`（见 §3）。**不写 DONE.json 等于没做完。**

## 2. 验证命令（backpressure，必须真跑）

```
python3 -m pytest -q
```

- 测试没过就不要声称完成。
- 不要为了通过而删测试、跳过测试或改断言。测试净减少会被审计者判为拒绝。

## 3. 完成信号（只认文件，不认你说的话）

编排器**不解析你的 stdout**。唯一被承认的完成信号是仓库根目录的 `DONE.json`：

```json
{
  "status": "done",
  "task": "T1",
  "files_changed": ["src/foo.py", "tests/test_foo.py"],
  "test_command": "python3 -m pytest -q",
  "test_exit_code": 0,
  "test_output": "12 passed in 0.41s",
  "notes": "为什么这么改，一句话"
}
```

`test_exit_code` 必须是**你刚跑出来的真实退出码**。编排器会自己再跑一遍对账，
对不上就记为作弊（`CLAIM_MISMATCH`），该轮直接判失败。

## 4. 不许碰

`.env*`、`secrets/`、`auth/`、`migrations/`、`gate.yaml`、`rsi/`（编排器自身源码）。
这些在文件系统层被 `rsi/gate.py` 机械拦截，不是靠你自觉。

## 5. 记忆

`memories.md` 是跨轮经验笔记，每轮会注入到你的上下文。踩过的坑记在那里，
不要指望下一轮的自己还记得这一轮的事。

## 6. 什么时候停

- 计划里所有复选框勾完 → 停。
- 连续 3 轮同一失败原因 → 编排器判僵局（STALEMATE），停。
- 看到根目录有 `LOOP_PAUSED` 文件 → 立即停，不要继续。

## 7. 自改（只有 meta 模式）

只有 `meta` 模式可以改 `prompts/*.md`、`memories.md`、`config/*.yaml`。
一次只改**一处**，diff 不超过 50 行。L1 阶段只写提案到 `proposals.md`，不自动应用。
