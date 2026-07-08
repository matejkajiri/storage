import json
import logging
import random
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
import os

from .exceptions import StorageCannotAcquireLock, StorageFileNotFoundError, StorageFileAlreadyExists


class Storage(ABC):
    """Abstract base class for any storage backend."""

    def __init__(self, collection: str, logger: logging.Logger | None = None, *args, **kwargs):
        if not collection:
            raise ValueError("Collection must be specified at construction")
        self._collection = collection.strip("/")
        self._logger = logger or logging.getLogger(__name__)

    # ---------------- PATH HANDLING ----------------
    def get_storage_full_path(self, relative_path: str) -> str:
        relative_path = relative_path.lstrip("/")
        return f"{self._collection}/{relative_path}" if self._collection else relative_path

    # ---------------- PUBLIC API ----------------
    def upload(self, remote_file_path: str, local_file_path: Path | str):
        return self._upload(self.get_storage_full_path(remote_file_path), local_file_path)

    def download(self, remote_file_path: str, local_file_path: Path | str):
        return self._download(self.get_storage_full_path(remote_file_path), local_file_path)

    def delete(self, remote_file_path: str):
        return self._delete(self.get_storage_full_path(remote_file_path))

    def exists(self, remote_file_path: str, expected_length: int | None = None) -> bool:
        return self._exists(self.get_storage_full_path(remote_file_path), expected_length)

    # ---------------- LOW-LEVEL IMPLEMENTATION ----------------
    @abstractmethod
    def _upload(self, remote_file_path: str, local_file_path: Path | str):
        ...

    @abstractmethod
    def _upload_atomic(self, remote_file_path: str, local_file_path: Path | str):
        ...

    @abstractmethod
    def _download(self, remote_file_path: str, local_file_path: Path | str):
        ...

    @abstractmethod
    def _delete(self, remote_file_path: str):
        ...

    @abstractmethod
    def _exists(self, remote_file_path: str, expected_length: int | None = None) -> bool:
        ...

    # ---------------- LOCKS ----------------
    @staticmethod
    def _get_lock_file_name(remote_file_path: str) -> str:
        return f"{remote_file_path}.lock"

    @contextmanager
    def locked(self, remote_file_path: str, max_retries: int = 10, ttl: int = 120):
        lock_id = None
        try:
            lock_id = self.acquire_lock(remote_file_path, max_retries, ttl)
            yield
        finally:
            if lock_id:
                try:
                    self.release_lock(remote_file_path, lock_id)
                except Exception as e:
                    self._logger.warning(f"Could not release lock for {remote_file_path}: {e}")
                    raise

    # ---------------- TEMP FILE CONTEXT MANAGER ----------------
    @contextmanager
    def _temp_path(self, suffix: str = ""):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        path = Path(tmp.name)
        tmp.close()
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    # ---------------- ACQUIRE / RELEASE LOCK ----------------
    def acquire_lock(self, remote_file_path: str, max_retries: int = 3, ttl: int = 120) -> str:
        lock_file_name = self._get_lock_file_name(remote_file_path)
        lock_id = str(uuid.uuid4())

        for attempt in range(max_retries):
            lock_data = {
                "uuid": lock_id,
                "timestamp": time.time(),
                "ttl": ttl,
                "pid": os.getpid()
            }

            with self._temp_path(".json") as tmp_lock_path:
                with open(tmp_lock_path, "w", encoding="utf-8") as f:
                    json.dump(lock_data, f, indent=2)

                try:
                    self._upload_atomic(lock_file_name, tmp_lock_path)
                    self._logger.info(f"Lock acquired for {remote_file_path} (ID: {lock_id})")
                    return lock_id

                except StorageFileAlreadyExists:
                    # Try again if failed in case of concurrent lock acquisition

                    if self._is_lock_expired(lock_file_name, ttl):
                        # Lock expired
                        self._logger.info(f"Lock expired for {remote_file_path}, deleting and retrying.")
                        self.delete(lock_file_name)
                        continue

                    else:
                        # Lock is still valid -> wait and try again
                        if attempt < max_retries - 1:
                            delay = 0.1 * (attempt + 1) + random.random()
                            time.sleep(delay)
                            continue
                        else:
                            raise

                except Exception as e:
                    # Other exceptions (network issues, etc.) should be propagated
                    if attempt < max_retries - 1:
                        time.sleep(0.5)
                        continue

                    raise

        raise StorageCannotAcquireLock(file=lock_file_name)

    def _is_lock_expired(self, lock_file_name: str, default_ttl: int) -> bool:
        try:
            with self._temp_path(".json") as verify_path:
                self.download(lock_file_name, verify_path)
                with open(verify_path, encoding="utf-8") as f:
                    content = json.load(f)

                timestamp = content.get("timestamp", 0)
                ttl = content.get("ttl", default_ttl)

                if (time.time() - timestamp) > ttl:
                    return True
                return False

        except StorageFileNotFoundError:
            # File does not exist; for safety reasons we assume it's not expired
            return False

        except Exception as e:
            # Some error occured; for safety reasons we assume it's not expired
            self._logger.warning(f"Error checking lock expiration for {lock_file_name}: {e}")
            return False

    def release_lock(self, remote_file_path: str, lock_id: str):
        lock_file_name = self._get_lock_file_name(remote_file_path)

        try:
            with self._temp_path(".json") as verify_path:
                self.download(lock_file_name, verify_path)

                with open(verify_path, encoding="utf-8") as f:
                    content = json.load(f)

                if content.get("uuid") == lock_id:
                    self.delete(lock_file_name)

                else:
                    self._logger.warning(f"Lock UUID mismatch for {lock_file_name}. Ignoring release.")

        except StorageFileNotFoundError:
            # Lock does not exist anymore (expired, removed by another process...)
            self._logger.debug(f"Lock file {lock_file_name} not found during release.")

        except Exception as e:
            self._logger.error(f"Error releasing lock {lock_file_name}: {e}")
            raise
