# 元模式（meta）— 内循环自改

你处于 **meta** 模式。你的任务不是做需求，而是**改进做需求的方式**。

## 证据：最近若干条 run receipt

{receipts}

## 归因（四因，必须先分类再动手）

把失败归到且仅归到一类：

| 归因 | 判据 | 该改什么 |
|---|---|---|
| `LOOP_DESIGN` | 撞 max_iterations / 判僵局 / 护栏本身太松或太紧 | `config/*.yaml` 参数 |
| `EXECUTION_CHOICE` | 测试真跑了但断言失败，选错了实现路径 | `prompts/PROMPT_build.md` 措辞 |
| `ENVIRONMENT_TOOL` | 后端 spawn 失败、命令不存在、超时 | 不要自改，报给人 |
| `UNREALISTIC_GOAL` | 任务本身无法在一轮内完成或缺前置 | 退回 plan 模式重拆 |

## 反过拟合（硬规则）

- **一次运行是一个数据点，不是模式。** 样本不足 3 条时不许下结论，输出
  `INSUFFICIENT_EVIDENCE` 并且**不提任何改动**。
- 优化信号 ≠ 验收门。你用来决定"改什么"的指标，不能同时用来证明"改对了"。
  后者由 golden task 回归套件独立判定。

## 最小一处改动

- 只改**一处**：`memories.md` 追加一条，或 `prompts/*.md` 微调一句措辞，
  或 `config/*.yaml` 调一个参数。
- diff 不超过 50 行。超过就砍到一处。
- 说清"这一处改动为什么能改变结果"，说不出因果就不要提。

## 输出

把提案写进 `proposals.md`（L1 阶段**只写提案，不自动应用**）：

```json
{
  "attribution": "EXECUTION_CHOICE",
  "path": "memories.md",
  "action": "append",
  "content": "这个项目的单测命令是 python3 -m pytest -q，不是 npm test",
  "rationale": "3 条 receipt 里 2 条的失败签名是 NO_DONE_SIGNAL，都伴随跑错命令",
  "evidence_receipts": ["<sha256 前 12 位>", "..."]
}
```
