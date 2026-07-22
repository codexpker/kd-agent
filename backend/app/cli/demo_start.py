import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StartupStep:
    name: str
    command: tuple[str, ...]
    working_directory: Path


def build_prepare_steps(
    repository_root: Path,
    python: str,
    docker: str,
) -> list[StartupStep]:
    backend = repository_root / "backend"
    return [
        StartupStep(
            "start_mysql_neo4j",
            (docker, "compose", "up", "-d", "--wait", "mysql", "neo4j"),
            repository_root,
        ),
        StartupStep(
            "upgrade_mysql_schema",
            (python, "-m", "alembic", "upgrade", "head"),
            backend,
        ),
        StartupStep(
            "sync_demo_seed",
            (
                python,
                "-m",
                "app.cli.ingest_gold",
                "--commit",
                "--sync-neo4j",
                "--force-graph-sync",
            ),
            backend,
        ),
    ]


def run_prepare_steps(steps: Sequence[StartupStep]) -> int:
    for index, step in enumerate(steps, start=1):
        print(f"[{index}/{len(steps)}] {step.name}", flush=True)
        result = subprocess.run(step.command, cwd=step.working_directory, check=False)
        if result.returncode:
            print(
                f"Demo preparation failed at {step.name} with exit code "
                f"{result.returncode}.",
                file=sys.stderr,
                flush=True,
            )
            return result.returncode
    return 0


def offline_backend_environment(source: dict[str, str]) -> dict[str, str]:
    environment = dict(source)
    environment.update(
        {
            "DOCUMENT_STRUCTURE_BACKEND": "gold",
            "EVIDENCE_GRAPH_BACKEND": "gold",
            "PRIVATE_PDF_PREVIEW_ENABLED": "false",
            "ASSISTANT_BACKEND": "offline",
            "ASSISTANT_SESSION_BACKEND": "memory",
            "PROJECT_CLAIM_BACKEND": "memory",
            "EXPERIMENT_RUN_BACKEND": "memory",
        }
    )
    return environment


def infrastructure_backend_environment(source: dict[str, str]) -> dict[str, str]:
    environment = dict(source)
    environment["ASSISTANT_SESSION_BACKEND"] = "mysql"
    return environment


def _read_url(url: str, timeout_seconds: float = 1.0) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            if response.status >= 400:
                return None
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def wait_for_url(url: str, timeout_seconds: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _read_url(url) is not None:
            return True
        time.sleep(0.25)
    return False


def _terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _readiness_status(url: str) -> tuple[str, dict[str, object] | None]:
    payload = _read_url(url, timeout_seconds=2.0)
    if payload is None:
        return "unreachable", None
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "invalid", None
    return str(parsed.get("status") or "invalid"), parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the KD Agent demo and open its guided golden flow."
    )
    parser.add_argument(
        "--with-infrastructure",
        action="store_true",
        help=(
            "explicitly start MySQL/Neo4j, migrate MySQL, and idempotently sync "
            "the demo seed before launching the app"
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="read the currently running demo readiness endpoint without writing or starting services",
    )
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repository_root = Path(__file__).resolve().parents[3]
    backend_root = repository_root / "backend"
    frontend_root = repository_root / "frontend"
    backend_origin = f"http://127.0.0.1:{args.backend_port}"
    frontend_origin = f"http://127.0.0.1:{args.frontend_port}"
    readiness_url = f"{backend_origin}/api/v1/demo/readiness"

    if args.check_only:
        status, payload = _readiness_status(readiness_url)
        print(f"status: {status}")
        if payload is not None:
            print(f"runtime_mode: {payload.get('runtime_mode', 'unknown')}")
            for check in payload.get("checks", []):
                if isinstance(check, dict):
                    print(
                        f"[{check.get('status', 'unknown')}] "
                        f"{check.get('check_id', 'unknown')}"
                    )
        return 0 if status == "ready" else 2

    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if npm is None:
        print("npm is required to start the Vue frontend.", file=sys.stderr)
        return 2

    if args.with_infrastructure:
        docker = shutil.which("docker")
        if docker is None:
            print("Docker is required for --with-infrastructure.", file=sys.stderr)
            return 2
        result = run_prepare_steps(
            build_prepare_steps(repository_root, sys.executable, docker)
        )
        if result:
            return result

    backend_process: subprocess.Popen[bytes] | None = None
    frontend_process: subprocess.Popen[bytes] | None = None
    backend_health = f"{backend_origin}/api/v1/healthz"
    try:
        if _read_url(backend_health) is None:
            backend_environment = (
                infrastructure_backend_environment(dict(os.environ))
                if args.with_infrastructure
                else offline_backend_environment(dict(os.environ))
            )
            backend_process = subprocess.Popen(
                (
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.backend_port),
                ),
                cwd=backend_root,
                env=backend_environment,
            )
            if not wait_for_url(backend_health):
                print("FastAPI did not become ready within 30 seconds.", file=sys.stderr)
                return 3
        else:
            print(f"Reusing running FastAPI at {backend_origin}.", flush=True)

        if _read_url(frontend_origin) is None:
            frontend_environment = dict(os.environ)
            frontend_environment["KD_AGENT_API_ORIGIN"] = backend_origin
            frontend_process = subprocess.Popen(
                (
                    npm,
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.frontend_port),
                ),
                cwd=frontend_root,
                env=frontend_environment,
            )
            if not wait_for_url(frontend_origin):
                print("Vue did not become ready within 30 seconds.", file=sys.stderr)
                return 4
        else:
            print(f"Reusing running Vue at {frontend_origin}.", flush=True)

        status, _ = _readiness_status(readiness_url)
        guide_url = f"{frontend_origin}/assistant?guide=1"
        print(f"Demo readiness: {status}", flush=True)
        print(f"Guided demo: {guide_url}", flush=True)
        if not args.no_open:
            webbrowser.open(guide_url)

        if backend_process is None and frontend_process is None:
            return 0 if status == "ready" else 2
        print("Press Ctrl+C to stop services started by this command.", flush=True)
        while True:
            if backend_process is not None and backend_process.poll() is not None:
                return backend_process.returncode or 5
            if frontend_process is not None and frontend_process.poll() is not None:
                return frontend_process.returncode or 6
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        _terminate(frontend_process)
        _terminate(backend_process)


if __name__ == "__main__":
    raise SystemExit(main())
