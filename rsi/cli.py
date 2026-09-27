"""Command-line entry point (report §5.2 ⑤ — the thin scheduler layer)."""

from __future__ import annotations

import argparse
import shlex
import sys
import tempfile
from pathlib import Path

from . import __version__
from .backend import CliBackend, StubBackend, detect_backend
from .blackboard import open_tasks, parse_plan
from .config import LoopConfig
from .gate import Gate
from .inner import InnerLoop
from .outer import OuterLoop
from .receipts import read_receipts, summarize, verify_integrity
from .regression import load_golden_tasks, run_golden_suite
from .vcs import GitVCS

__all__ = ["main", "build_parser"]

DEFAULT_BACKEND_ARGV = "claude -p --dangerously-skip-permissions --output-format stream-json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rsi",
        description="Recursive self-improvement loop orchestrator (thin glue over coding CLIs).",
    )
    parser.add_argument("--version", action="version", version=f"rsi {__version__}")
    parser.add_argument(
        "--project", default="loop-project", help="project root (default: loop-project)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="report environment, config, gate and plan status")

    p_run = sub.add_parser("run", help="run the outer loop")
    p_run.add_argument("--backend-argv", default=DEFAULT_BACKEND_ARGV)
    p_run.add_argument("--max-tasks", type=int, default=0)
    p_run.add_argument("--no-git", action="store_true", help="do not commit snapshots")
    p_run.add_argument("--no-audit", action="store_true")

    sub.add_parser("meta", help="run the inner self-improvement loop")

    p_gate = sub.add_parser("gate-check", help="check whether paths may be self-modified")
    p_gate.add_argument("paths", nargs="+")
    p_gate.add_argument("--diff-lines", type=int, default=None)

    p_rec = sub.add_parser("receipts", help="show recent run receipts")
    p_rec.add_argument("--limit", type=int, default=10)

    p_reg = sub.add_parser("regress", help="run the golden-task regression suite")
    p_reg.add_argument("--suite", default="golden/tasks")

    return parser


def _load(project: Path) -> tuple[LoopConfig, Gate]:
    config = LoopConfig.load(project / "config" / "loop.yaml")
    gate = Gate.load(project / config.gate_file)
    return config, gate


def cmd_doctor(project: Path, _args: argparse.Namespace) -> int:
    config, gate = _load(project)
    plan_path = project / config.plan_file
    tasks = parse_plan(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else []
    receipts = read_receipts(project / config.receipts_file)
    tampered = [r for r in receipts if not verify_integrity(r)]

    print(f"rsi {__version__}")
    print(f"project            : {project}")
    print(f"python             : {sys.version.split()[0]}")
    print(f"backend on PATH    : {detect_backend()}")
    print(f"config             : {config.source}")
    print(f"gate               : {gate.source}")
    print(f"gate allow         : {len(gate.allow)} pattern(s), deny {len(gate.deny)} "
          f"+ {len(gate.hard_deny)} hardcoded")
    print(f"autonomy level     : {config.autonomy_level}")
    print(f"plan               : {len(open_tasks(tasks))} open / {len(tasks)} total")
    print(f"receipts           : {len(receipts)} "
          f"({'ALL PINNED' if not tampered else f'{len(tampered)} TAMPERED'})")
    print(f"inner loop triggers: {InnerLoop(project, config, gate).should_trigger()}")
    if receipts:
        print(f"metrics            : {summarize(receipts)}")
    return 0


def cmd_run(project: Path, args: argparse.Namespace) -> int:
    config, gate = _load(project)
    if args.max_tasks:
        config.max_tasks = args.max_tasks
    if args.no_audit:
        config.auditor_enabled = False

    available = detect_backend()
    if available == "none":
        print(
            "error: no coding CLI found on PATH "
            f"(looked for: claude/codex/opencode/gemini).\n"
            f"Install one, or point --backend-argv at your own. "
            f"Configured argv was: {args.backend_argv!r}",
            file=sys.stderr,
        )
        return 2

    from .audit import Auditor  # local import keeps `doctor` dependency-free

    backend = CliBackend(argv=shlex.split(args.backend_argv))
    auditor = Auditor(
        backend=CliBackend(argv=shlex.split(args.backend_argv)),
        test_commands=config.test_commands,
        prompt_template=(project / config.prompt_path("audit")).read_text(encoding="utf-8")
        if (project / config.prompt_path("audit")).exists()
        else "",
        timeout_s=config.timeout_s,
        audit_file=config.audit_file,
        count_command=config.count_command or None,
    )
    vcs = GitVCS(project) if not args.no_git else None
    loop = OuterLoop(project, backend, config=config, gate=gate, vcs=vcs, auditor=auditor)
    summary = loop.run()

    for outcome in summary.outcomes:
        print(f"{outcome.task_id}: {outcome.terminal_state} "
              f"({outcome.iterations} iter, {outcome.tokens} tok)"
              + (f" CHEAT" if outcome.cheat_detected else ""))
    print(f"summary: {summary.terminal_state} exit={summary.exit_code} "
          f"cost=${summary.total_cost_usd:.4f}")
    return summary.exit_code


def cmd_meta(project: Path, _args: argparse.Namespace) -> int:
    config, gate = _load(project)
    vcs = GitVCS(project)
    result = InnerLoop(project, config, gate, vcs).run()

    print(f"window          : {result.debrief.sample_size} receipt(s)")
    print(f"attribution     : {result.debrief.attribution} ({result.debrief.reason})")
    print(f"autonomy        : {result.autonomy_level}")
    if result.proposal is None:
        print("proposal        : none — evidence does not justify a self-change")
        return 0
    print(f"proposal        : {result.proposal.action} -> {result.proposal.path} "
          f"({result.proposal.risk} risk, {result.proposal.diff_lines} diff lines)")
    print(f"applied         : {result.apply_result.applied} ({result.apply_result.reason})")
    print(f"recorded        : {result.proposal_recorded}")
    return 0


def cmd_gate_check(project: Path, args: argparse.Namespace) -> int:
    _config, gate = _load(project)
    verdict = gate.check(args.paths, diff_lines=args.diff_lines)
    print(verdict.explain())
    for violation in verdict.violations:
        print(f"  - {violation}")
    return 0 if verdict.allowed else 1


def cmd_receipts(project: Path, args: argparse.Namespace) -> int:
    config, _gate = _load(project)
    rows = read_receipts(project / config.receipts_file)
    for row in rows[-args.limit :]:
        flag = "" if verify_integrity(row) else "  [TAMPERED]"
        print(f"{row.get('sha256', '')[:12]}  {row.get('terminal_state'):<22} "
              f"iter={row.get('iterations')} tok={row.get('tokens')} "
              f"sig={row.get('failure_signature') or '-'}{flag}")
    print(f"{len(rows)} receipt(s); metrics: {summarize(rows)}")
    return 0


def cmd_regress(project: Path, args: argparse.Namespace) -> int:
    config, gate = _load(project)
    tasks = load_golden_tasks(args.suite)
    if not tasks:
        print(f"error: no golden tasks found under {args.suite}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="rsi-regress-") as tmp:
        result = run_golden_suite(tasks, config, Path(tmp), gate=gate)
    for task_id, state in result.per_task.items():
        print(f"{task_id}: {state}")
    for mismatch in result.mismatches:
        print(f"MISMATCH {mismatch}")
    print(f"metrics: {result.metrics}")
    return 1 if result.mismatches else 0


_HANDLERS = {
    "doctor": cmd_doctor,
    "run": cmd_run,
    "meta": cmd_meta,
    "gate-check": cmd_gate_check,
    "receipts": cmd_receipts,
    "regress": cmd_regress,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _HANDLERS[args.command](Path(args.project), args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
