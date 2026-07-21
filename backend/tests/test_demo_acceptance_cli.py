from pathlib import Path

from app.cli.demo_acceptance import AcceptanceStep, build_steps, run_steps


def test_demo_acceptance_plan_keeps_infrastructure_explicit(tmp_path: Path) -> None:
    offline = build_steps(
        tmp_path,
        "python-test",
        "npm-test",
        with_infrastructure=False,
    )
    full = build_steps(
        tmp_path,
        "python-test",
        "npm-test",
        with_infrastructure=True,
    )

    assert [step.name for step in offline] == [
        "backend_tests",
        "frontend_production_build",
        "offline_browser_golden_flow",
    ]
    assert [step.name for step in full] == [
        *[step.name for step in offline],
        "mysql_neo4j_r2_acceptance",
        "real_infrastructure_browser_flow",
    ]
    assert all(step.command[0] in {"python-test", "npm-test"} for step in full)


def test_demo_acceptance_stops_at_first_failure(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command, *, cwd, check):
        calls.append(tuple(command))

        class Result:
            returncode = 7 if command[1] == "second" else 0

        return Result()

    monkeypatch.setattr("app.cli.demo_acceptance.subprocess.run", fake_run)
    steps = [
        AcceptanceStep("first", ("tool", "first"), tmp_path),
        AcceptanceStep("second", ("tool", "second"), tmp_path),
        AcceptanceStep("third", ("tool", "third"), tmp_path),
    ]

    assert run_steps(steps) == 7
    assert calls == [("tool", "first"), ("tool", "second")]
