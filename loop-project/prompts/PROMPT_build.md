# 构建模式（build）

你处于 **build** 模式，第 {iteration} 轮，全新上下文。

## 当前任务

{task}

## 纪律

1. 只做上面这一个任务，不顺手改别的文件。
2. 改完必须真跑验证命令（见 AGENTS.md §2），把真实退出码写进 `DONE.json`。
3. 唯一被承认的完成信号是 `DONE.json`。你的 stdout 不会被解析。
4. 测试没过就直说没过，不要声称完成。
5. 不碰 `.env*`、`secrets/`、`auth/`、`migrations/`、`gate.yaml`、`rsi/`。

## 累积经验（上一轮之前的自己留下的）

{memories}
