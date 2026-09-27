# 规格示例：calculator 除法语义收敛

## 背景

`loop-project/` 里的示例目标是一个只含 `divide` 的极小模块。它是外循环的靶子，
作用是让 backpressure 有真实的测试可跑。

## 需求

`divide(a, b)` 必须满足：

1. 返回真正的浮点商（当前实现是整除 `a // b`，`divide(7, 2)` 得到 `3` 而非 `3.5`）；
2. `b == 0` 时抛 `ValueError`，而不是让 `ZeroDivisionError` 漏出去；
3. 三条需求各有一条单测覆盖。

## 验收（客观命令）

```
python3 -m pytest -q test_calculator.py
python3 -m pytest -q --collect-only test_calculator.py   # 净减少守卫的基线来源
```

## 拆分（写入 IMPLEMENTATION_PLAN.md）

- T1 补零除异常与 5 个单测
- T2 返回值统一为 float
- T3 补类型注解并过 mypy --strict

## 显式假设

- 目标仓库已有可跑的 pytest（backpressure 的前提，报告 §7.1）。
- 每条任务应在一轮 fresh context 内可完成；做不到就退回 plan 模式重拆
  （报告 §6 第 3 阶段的 `UNREALISTIC_GOAL` 归因）。
