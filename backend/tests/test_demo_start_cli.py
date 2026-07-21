from pathlib import Path

from app.cli.demo_start import (
    StartupStep,
    build_prepare_steps,
    offline_backend_environment,
    parse_args,
    run_prepare_steps,
)


def test_offline_start_does_not_enable_external_dependencies() -> None:
    environment = offline_backend_environment({"KEEP_ME": "yes"})

    assert environment["KEEP_ME"] == "yes"
    assert environment["DOCUMENT_STRUCTURE_BACKEND"] == "gold"
    assert environment["EVIDENCE_GRAPH_BACKEND"] == "gold"
    assert environment["PRIVATE_PDF_PREVIEW_ENABLED"] == "false"
    assert environment["ASSISTANT_BACKEND"] == "offline"


def test_infrastructure_preparation_is_explicit_and_idempotent(tmp_path: Path) -> None:
    assert parse_args([]).with_infrastructure is False
    steps = build_prepare_steps(tmp_path, "python-test", "docker-test")

    assert [step.name for step in steps] == [
        "start_mysql_neo4j",
        "upgrade_mysql_schema",
        "sync_demo_seed",
    ]
    assert steps[0].command == (
        "docker-test",
        "compose",
        "up",
        "-d",
        "--wait",
        "mysql",
        "neo4j",
    )
    assert "--commit" in steps[-1].command
    assert "--force-graph-sync" in steps[-1].command


def test_prepare_stops_at_first_failure(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command, *, cwd, check):
        calls.append(tuple(command))

        class Result:
            returncode = 8 if command[1] == "second" else 0

        return Result()

    monkeypatch.setattr("app.cli.demo_start.subprocess.run", fake_run)
    steps = [
        StartupStep("first", ("tool", "first"), tmp_path),
        StartupStep("second", ("tool", "second"), tmp_path),
        StartupStep("third", ("tool", "third"), tmp_path),
    ]

    assert run_prepare_steps(steps) == 8
    assert calls == [("tool", "first"), ("tool", "second")]
