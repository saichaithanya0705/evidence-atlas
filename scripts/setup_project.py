"""Prepare the demo application and run its API and Vite development server.

``start.bat`` bootstraps the Windows virtual environment and dependencies before
calling this script. The script deliberately runs setup stages in order and owns
the server process trees so Ctrl+C and startup errors do not leave them running.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
LOGS_ROOT = PROJECT_ROOT / "logs"


def _step(label: str, command: list[str], cwd: Path = PROJECT_ROOT, dry_run: bool = False) -> None:
    printable = subprocess.list2cmdline(command) if os.name == "nt" else " ".join(command)
    print(f"\n== {label} ==\n{printable}", flush=True)
    if dry_run:
        return
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")


def _npm_command(*args: str) -> list[str]:
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        npm = shutil.which("npm.cmd") or "npm.cmd"
        command = subprocess.list2cmdline([npm, *args])
        return [comspec, "/d", "/s", "/c", command]
    return ["npm", *args]


def _ensure_node_path() -> None:
    """Make a standard per-user Node installation visible to npm subprocesses."""
    npm_name = "npm.cmd" if os.name == "nt" else "npm"
    if not (shutil.which("node") and shutil.which(npm_name)) and os.name == "nt":
        for directory in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs", Path(os.environ.get("ProgramFiles", "")) / "nodejs"):
            if (directory / "node.exe").is_file() and (directory / "npm.cmd").is_file():
                os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
                break
    node = shutil.which("node")
    npm = shutil.which(npm_name)
    if not node or not npm:
        raise RuntimeError("Node.js and npm are required. Install Node.js 22.12+ and reopen the terminal.")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
    supported = bool(match) and (int(match.group(1)) == 20 and int(match.group(2)) >= 19 or int(match.group(1)) == 22 and int(match.group(2)) >= 12 or int(match.group(1)) >= 23)
    if not supported:
        raise RuntimeError(f"Node {version} is unsupported by Vite. Install Node.js 20.19+ or 22.12+ and reopen the terminal.")


def _indices_ready() -> bool:
    """Reuse an intact index only when its corpus and source have not changed."""
    raw = PROJECT_ROOT / "data/raw/pubmed_sample.csv"
    cleaned = PROJECT_ROOT / "data/processed/cleaned_pubmed.parquet"
    preprocessing = PROJECT_ROOT / "data/manifests/preprocessing_manifest.json"
    index = PROJECT_ROOT / "data/manifests/index_manifest.json"
    required = [raw, cleaned, preprocessing, index,
                PROJECT_ROOT / "data/processed/cleaned_pubmed.jsonl",
                PROJECT_ROOT / "data/processed/article_embeddings.npy",
                PROJECT_ROOT / "data/processed/bm25_index.pkl",
                PROJECT_ROOT / "data/processed/mesh_dictionary.json",
                PROJECT_ROOT / "data/processed/mesh_graph.gpickle",
                PROJECT_ROOT / "data/qdrant_storage/collection"]
    if not all(path.exists() for path in required):
        return False
    if raw.stat().st_mtime > preprocessing.stat().st_mtime or cleaned.stat().st_mtime > index.stat().st_mtime:
        return False
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
        expected = data["corpus"]["sha256"]
        points = data["vector_store"]["points_count"]
        if points <= 0 or points != data["corpus"]["total_records"]:
            return False
        digest = hashlib.sha256()
        with cleaned.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _ensure_first_administrator() -> None:
    from backend.app.core.config import get_settings
    from backend.app.storage.accounts import AccountStore
    from backend.app.storage.database import initialize_db

    path = get_settings().APP_DATABASE_PATH
    initialize_db(path)
    if AccountStore(path).list_accounts(limit=1)["total"]:
        return
    if not sys.stdin.isatty():
        raise RuntimeError("No administrator exists. Run: .venv\\Scripts\\python.exe scripts\\manage_accounts.py bootstrap-admin --username administrator")
    print("\nFirst-time account setup: create the administrator before the servers start.", flush=True)
    _step("Create first administrator", [sys.executable, "scripts/manage_accounts.py", "bootstrap-admin", "--username", "administrator"])


def _preflight(dry_run: bool) -> None:
    if not dry_run and not (FRONTEND_ROOT / "package.json").is_file():
        raise FileNotFoundError(f"Vite application manifest not found: {FRONTEND_ROOT / 'package.json'}")
    if not dry_run and not (PROJECT_ROOT / ".env").is_file():
        raise FileNotFoundError(".env is missing. Run start.bat so it can copy .env.example first.")


def _read_setting(name: str, default: str) -> str:
    env_file = PROJECT_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("\"'") or default
    return os.environ.get(name, default)


def _port_open(url: str) -> bool:
    try:
        with urlopen(url, timeout=1) as response:
            if response.status != 200:
                return False
            if url.endswith("/health"):
                return json.loads(response.read().decode("utf-8")).get("status") == "healthy"
            return True
    except (OSError, URLError, ValueError):
        return False


def _cleanup_process(process: subprocess.Popen, label: str) -> None:
    if process.poll() is not None:
        return
    print(f"Stopping {label} (PID {process.pid})...", flush=True)
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    else:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _start_servers(dry_run: bool = False) -> None:
    api_host = _read_setting("HOST", "127.0.0.1")
    api_port = _read_setting("PORT", "8000")
    web_port = "5173"
    python = sys.executable
    backend_command = [python, "-m", "uvicorn", "backend.app.main:app", "--host", api_host, "--port", api_port]
    frontend_command = _npm_command("run", "dev", "--", "--host", "127.0.0.1", "--strictPort")
    for label, command in (("Start FastAPI", backend_command), ("Start Vite", frontend_command)):
        printable = subprocess.list2cmdline(command) if os.name == "nt" else " ".join(command)
        print(f"\n== {label} ==\n{printable}", flush=True)
    if dry_run:
        return

    LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    backend_log = (LOGS_ROOT / "backend.log").open("a", encoding="utf-8")
    frontend_log = (LOGS_ROOT / "frontend.log").open("a", encoding="utf-8")
    process_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    processes: list[tuple[str, subprocess.Popen]] = []
    try:
        api = subprocess.Popen(
            backend_command,
            cwd=PROJECT_ROOT,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            creationflags=process_flags,
        )
        processes.append(("FastAPI", api))

        health_url = f"http://127.0.0.1:{api_port}/health"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if api.poll() is not None:
                raise RuntimeError(f"FastAPI exited during startup (code {api.returncode}); see logs/backend.log")
            if _port_open(health_url):
                break
            time.sleep(0.4)
        else:
            raise RuntimeError(f"FastAPI did not become healthy at {health_url}; see logs/backend.log")

        web = subprocess.Popen(
            frontend_command,
            cwd=FRONTEND_ROOT,
            env={**os.environ, "VITE_BACKEND_PORT": api_port},
            stdout=frontend_log,
            stderr=subprocess.STDOUT,
            creationflags=process_flags,
        )
        processes.append(("Vite", web))
        web_url = f"http://127.0.0.1:{web_port}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if api.poll() is not None:
                raise RuntimeError(f"FastAPI stopped unexpectedly (code {api.returncode}); see logs/backend.log")
            if web.poll() is not None:
                raise RuntimeError(f"Vite exited during startup (code {web.returncode}); see logs/frontend.log")
            if _port_open(web_url):
                break
            time.sleep(0.4)
        else:
            raise RuntimeError(f"Vite did not become available at {web_url}; see logs/frontend.log")

        print(f"\nApplication is ready: {web_url} (API health: {health_url})", flush=True)
        print("Press Ctrl+C to stop both services.", flush=True)
        while True:
            for label, process in processes:
                if process.poll() is not None:
                    raise RuntimeError(f"{label} stopped unexpectedly (code {process.returncode}); check logs/.")
            time.sleep(0.5)
    finally:
        for label, process in reversed(processes):
            _cleanup_process(process, label)
        backend_log.close()
        frontend_log.close()


def prepare_and_run(offline: bool = False, dry_run: bool = False) -> None:
    _preflight(dry_run)
    if not dry_run:
        _ensure_node_path()
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["MEDCPT_ALLOW_MOCK"] = "true"
        print("OFFLINE MODEL MODE: MedCPT downloads are disabled; uncached models use marked mock embeddings. npm may still contact its package registry.", flush=True)
    else:
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ["TRANSFORMERS_OFFLINE"] = "0"
        os.environ["MEDCPT_ALLOW_MOCK"] = "false"

    python = sys.executable
    setup_command = [python, "scripts/setup_assets.py"] + (["--offline"] if offline else [])
    pipeline_commands = [
        ("Profile source corpus", [python, "pipelines/inspect_dataset.py", "--input", "data/raw/pubmed_sample.csv", "--output", "data/manifests/dataset_profile.json"]),
        ("Preprocess corpus", [python, "pipelines/preprocess.py", "--input", "data/raw/pubmed_sample.csv", "--output-parquet", "data/processed/cleaned_pubmed.parquet", "--output-jsonl", "data/processed/cleaned_pubmed.jsonl", "--manifest", "data/manifests/preprocessing_manifest.json"]),
        (
            "Build MedCPT article embeddings",
            [
                python,
                "pipelines/build_embeddings.py",
                "--input",
                "data/processed/cleaned_pubmed.parquet",
                "--output-dir",
                "data/processed",
                "--resume",
                "--checkpoint-every",
                "10",
            ],
        ),
        ("Build BM25 index", [python, "pipelines/build_bm25.py", "--corpus", "data/processed/cleaned_pubmed.parquet", "--output", "data/processed/bm25_index.pkl"]),
        ("Build MeSH dictionary", [python, "pipelines/build_mesh_dict.py", "--input", "data/processed/cleaned_pubmed.jsonl", "--output", "data/processed/mesh_dictionary.json"]),
        ("Build paper-MeSH graph", [python, "pipelines/build_mesh_graph.py", "--input", "data/processed/cleaned_pubmed.jsonl", "--output-pickle", "data/processed/mesh_graph.gpickle", "--output-json", "data/processed/mesh_graph.json", "--manifest", "data/manifests/graph_manifest.json"]),
        ("Build embedded Qdrant collection", [python, "pipelines/index_qdrant.py", "--corpus", "data/processed/cleaned_pubmed.parquet", "--embeddings", "data/processed/article_embeddings.npy", "--qdrant-path", "data/qdrant_storage", "--bm25-file", "data/processed/bm25_index.pkl", "--manifest-output", "data/manifests/index_manifest.json"]),
    ]

    if dry_run:
        _step("Download/verify MedCPT models and prepare dataset", setup_command, dry_run=True)
        for label, command in pipeline_commands:
            _step(label, command, dry_run=True)
        _step("Install frontend dependencies", _npm_command("install"), cwd=FRONTEND_ROOT, dry_run=True)
        _start_servers(dry_run=True)
        return

    _step("Download/verify MedCPT models and prepare dataset", setup_command)
    if not os.environ.get("PUBMED_FORCE_REINDEX") and _indices_ready():
        print("Existing PubMed index matches the processed corpus; skipping repeated indexing.", flush=True)
    else:
        for label, command in pipeline_commands:
            _step(label, command)
    _step("Install frontend dependencies", _npm_command("install"), cwd=FRONTEND_ROOT)
    _ensure_first_administrator()
    _start_servers()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Use local cached models only and allow explicitly marked mock embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Print the setup/startup commands without changing files or starting services")
    parser.add_argument("--check-runtime", action="store_true", help="Check Node/npm before dependency downloads or indexing")
    args = parser.parse_args(argv)

    def stop_on_terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_terminate)
    try:
        if args.check_runtime:
            _ensure_node_path()
            print("Node.js and npm preflight passed.", flush=True)
        else:
            prepare_and_run(offline=args.offline, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\nShutdown requested.", flush=True)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"\nStartup failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
