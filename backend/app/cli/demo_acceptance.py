import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AcceptanceStep:
    name: str
    command: tuple[str, ...]
    working_directory: Path


def build_steps(
    repository_root: Path,
    python: str,
    npm: str,
    *,
    with_infrastructure: bool,
) -> list[AcceptanceStep]:
    backend = repository_root / "backend"
    frontend = repository_root / "frontend"
    steps = [
        AcceptanceStep(
            name="backend_tests",
            command=(python, "-m", "pytest", "-q"),
            working_directory=backend,
        ),
        AcceptanceStep(
            name="frontend_production_build",
            command=(npm, "run", "build"),
            working_directory=frontend,
        ),
        AcceptanceStep(
            name="offline_browser_golden_flow",
            command=(npm, "run", "test:e2e"),
            working_directory=frontend,
        ),
    ]
    if with_infrastructure:
        steps.append(
            AcceptanceStep(
                name="mysql_neo4j_r2_acceptance",
                command=(python, "-m", "app.cli.r2_acceptance"),
                working_directory=backend,
            )
        )
    return steps


def run_steps(steps: list[AcceptanceStep]) -> int:
    for index, step in enumerate(steps, start=1):
        print(f"[{index}/{len(steps)}] {step.name}", flush=True)
        result = subprocess.run(
            step.command,
            cwd=step.working_directory,
            check=False,
        )
        if result.returncode:
            print(
                f"Demo acceptance failed at {step.name} with exit code "
                f"{result.returncode}.",
                file=sys.stderr,
                flush=True,
            )
            return result.returncode
    print("Demo acceptance passed.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the repeatable KD Agent demo acceptance gate."
    )
    parser.add_argument(
        "--with-infrastructure",
        action="store_true",
        help="also run the real MySQL/Neo4j R2 acceptance",
    )
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[3]
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if npm is None:
        print("npm is required for the frontend acceptance steps.", file=sys.stderr)
        return 2
    steps = build_steps(
        repository_root,
        sys.executable,
        npm,
        with_infrastructure=args.with_infrastructure,
    )
    return run_steps(steps)


if __name__ == "__main__":
    raise SystemExit(main())
