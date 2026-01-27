from pathlib import Path


class StorageError(Exception):
    """Base exception for storage-related errors."""
    pass


class StorageCannotAcquireLock(StorageError):
    """Raised when a file lock cannot be acquired."""
    def __init__(self, file: Path | str | None = None):
        message = "Cannot acquire file lock!"
        if file is not None:
            message += f" Lock file: {file}"
        super().__init__(message)


class StorageFileNotFoundError(StorageError):
    """Raised when a file is not found in storage."""
    def __init__(self, file: Path | str | None = None):
        message = "File not found!"
        if file is not None:
            message = f"File {file} not found!"
        super().__init__(message)


class S3Error(StorageError):
    """Base exception for S3-related errors."""
    pass


class S3BucketNotSpecified(S3Error):
    """Raised when S3 bucket is not specified at construction."""
    def __init__(self):
        super().__init__("S3 Bucket not specified!")
