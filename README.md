# Storage

Reusable Python storage abstraction with S3 implementation.
Provides a simple interface to work with any storage backend through an abstract Storage class and a concrete S3 implementation.

## Installation

### Install directly from GitHub

```bash
pip install git+https://github.com/matejkajiri/storage.git
```

---

## Usage

### Import

```python
from storage import *
```

### Using S3 Storage

#### Initialization

```python
s3 = S3(
    s3_host="https://my-s3-endpoint",
    access_key="ACCESS_KEY", # Can be ommited if using .env variables: "AWS_ACCESS_KEY_ID"
    secret_key="SECRET_KEY", # Can be ommited if using .env variables: "AWS_SECRET_KEY_ID"
    host_bucket="my-bucket",
    collection="my-collection"
)
```

#### Upload a file

```python
s3.upload("remote/file.txt", "local/file.txt")
```

#### Download a file

```python
s3.download("remote/file.txt", "local/file.txt")
```

#### Check if a file exists

```python
if s3.exists("remote/file.txt"):
    print("File exists!")
```

#### Delete a file

```python
s3.delete("remote/file.txt")
```

---

### Using the lock mechanism

The package supports file locks to safely access the same file from multiple processes:

```python
try:
    with s3.locked("remote/file.txt"):
        # Only one process at a time can work with this file
        s3.upload("remote/file.txt", "local/file.txt")
except StorageCannotAcquireLock:
    print("Could not acquire lock on file!")
```

The lock is automatically released after leaving the with block.

If the lock cannot be acquired after max_retries, a StorageCannotAcquireLock exception is raised.

---

### Exception handling

- `StorageFileNotFoundError` – the file does not exist in storage.
- `StorageCannotAcquireLock` – failed to acquire a lock.
- `S3BucketNotSpecified` – S3 bucket not specified at construction.
- `S3Error` – general S3 error.
- `StorageError` – general storage error.

---

## Notes

Uses standard Python libraries and `boto3` for S3 support.

Supports temporary files and file locks for safe concurrent access.
