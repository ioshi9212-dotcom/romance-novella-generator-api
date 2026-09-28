import json
import os
import shutil
import tempfile
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

try:
    import fcntl
except ImportError:  # pragma: no cover - Railway runs on Linux.
    fcntl = None


def safe_component(value: str, label: str = "path component") -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if len(value) > 160 or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{label} is not a safe path component")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} contains control characters")
    return value


def safe_relative_path(value: str) -> Path:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("relative path must be non-empty")
    if "\\" in value or any(ord(char) < 32 for char in value):
        raise ValueError("relative path is unsafe")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("relative path is unsafe")
    return path


class JsonStorage:
    _locks_guard = threading.Lock()
    _locks: ClassVar[dict[str, threading.RLock]] = {}
    _local = threading.local()

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _process_lock(cls, key: str) -> threading.RLock:
        with cls._locks_guard:
            lock = cls._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                cls._locks[key] = lock
            return lock

    def session_dir(self, session_id: str) -> Path:
        safe_id = safe_component(session_id, "session_id")
        root = self.sessions_dir.resolve()
        path = (root / safe_id).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:  # pragma: no cover - guarded by safe_component.
            raise ValueError("session path escaped the sessions directory") from exc
        return path

    def session_exists(self, session_id: str) -> bool:
        return self.session_dir(session_id).is_dir()

    def create_session_dir(self, session_id: str) -> Path:
        path = self.session_dir(session_id)
        path.mkdir(parents=False, exist_ok=False)
        return path

    def _path(self, session_id: str, relative: str) -> Path:
        session_root = self.session_dir(session_id)
        path = (session_root / safe_relative_path(relative)).resolve()
        try:
            path.relative_to(session_root)
        except ValueError as exc:
            raise ValueError("file path escaped the session directory") from exc
        return path

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_text_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, path)
            self._fsync_dir(path.parent)
        except Exception:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _copy_synced(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (
            source.open("rb") as source_handle,
            destination.open("wb") as target_handle,
        ):
            shutil.copyfileobj(source_handle, target_handle)
            target_handle.flush()
            os.fsync(target_handle.fileno())

    def _rollback(
        self, session_root: Path, transaction_dir: Path, manifest: dict[str, Any]
    ) -> None:
        entries = manifest.get("entries", []) if isinstance(manifest, dict) else []
        for entry in reversed(entries):
            target = (session_root / safe_relative_path(str(entry["target"]))).resolve()
            target.relative_to(session_root)
            if entry.get("backup_exists"):
                backup = transaction_dir / str(entry["backup"])
                if not backup.exists():
                    raise RuntimeError(
                        f"missing transaction backup for {entry['target']}"
                    )
                self._write_text_atomic(target, backup.read_text(encoding="utf-8"))
            else:
                target.unlink(missing_ok=True)
                self._fsync_dir(target.parent)
        shutil.rmtree(transaction_dir, ignore_errors=True)

    def _recover(self, session_root: Path) -> None:
        transactions_root = session_root / ".transactions"
        if not transactions_root.exists():
            return
        for transaction_dir in sorted(
            path for path in transactions_root.iterdir() if path.is_dir()
        ):
            manifest_path = transaction_dir / "manifest.json"
            if not manifest_path.exists():
                shutil.rmtree(transaction_dir, ignore_errors=True)
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("state") == "committed":
                shutil.rmtree(transaction_dir, ignore_errors=True)
            else:
                self._rollback(session_root, transaction_dir, manifest)
        try:
            transactions_root.rmdir()
        except OSError:
            pass

    @contextmanager
    def session_transaction(self, session_id: str) -> Iterator[None]:
        session_root = self.session_dir(session_id)
        if not session_root.exists():
            raise FileNotFoundError(session_id)
        key = str(session_root)
        active = getattr(self._local, "active", set())
        if key in active:
            yield
            return

        process_lock = self._process_lock(key)
        with process_lock:
            lock_path = session_root / ".session.lock"
            lock_path.touch(exist_ok=True)
            with lock_path.open("a+") as lock_handle:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                active = set(getattr(self._local, "active", set()))
                active.add(key)
                self._local.active = active
                try:
                    self._recover(session_root)
                    yield
                finally:
                    active = set(getattr(self._local, "active", set()))
                    active.discard(key)
                    self._local.active = active
                    if fcntl is not None:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def read_json(self, session_id: str, relative: str, default: Any = None) -> Any:
        path = self._path(session_id, relative)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json_batch(self, session_id: str, values: dict[str, Any]) -> None:
        if not values:
            return
        with self.session_transaction(session_id):
            self._write_json_batch_locked(session_id, values)

    def _write_json_batch_locked(self, session_id: str, values: dict[str, Any]) -> None:
        session_root = self.session_dir(session_id)
        transactions_root = session_root / ".transactions"
        transaction_dir = transactions_root / uuid.uuid4().hex
        staged_dir = transaction_dir / "staged"
        backup_dir = transaction_dir / "backup"
        staged_dir.mkdir(parents=True, exist_ok=False)
        backup_dir.mkdir(parents=True, exist_ok=True)

        manifest: dict[str, Any] = {"version": 1, "state": "prepared", "entries": []}
        manifest_path = transaction_dir / "manifest.json"
        try:
            for index, relative in enumerate(sorted(values)):
                target = self._path(session_id, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                staged = staged_dir / f"{index:04d}.json"
                backup = backup_dir / f"{index:04d}.json"
                content = (
                    json.dumps(values[relative], ensure_ascii=False, indent=2) + "\n"
                )
                self._write_text_atomic(staged, content)
                backup_exists = target.exists()
                if backup_exists:
                    self._copy_synced(target, backup)
                manifest["entries"].append(
                    {
                        "target": relative,
                        "staged": str(staged.relative_to(transaction_dir)),
                        "backup": str(backup.relative_to(transaction_dir)),
                        "backup_exists": backup_exists,
                    }
                )

            self._write_text_atomic(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            self._fsync_dir(transaction_dir)

            for entry in manifest["entries"]:
                target = self._path(session_id, entry["target"])
                staged = transaction_dir / entry["staged"]
                os.replace(staged, target)
                self._fsync_dir(target.parent)

            manifest["state"] = "committed"
            self._write_text_atomic(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            shutil.rmtree(transaction_dir, ignore_errors=True)
            try:
                transactions_root.rmdir()
            except OSError:
                pass
        except Exception:
            if manifest_path.exists():
                self._rollback(session_root, transaction_dir, manifest)
            else:
                shutil.rmtree(transaction_dir, ignore_errors=True)
            raise
