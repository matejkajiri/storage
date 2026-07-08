import logging
import os
from pathlib import Path

import boto3
import botocore.exceptions
from botocore.config import Config

from . import StorageFileAlreadyExists
from .exceptions import S3Error, S3BucketNotSpecified, StorageFileNotFoundError
from .storage import Storage


class S3(Storage):
    """S3 storage implementation using boto3."""

    def __init__(
            self,
            s3_host: str | None = None,
            access_key: str | None = None,
            secret_key: str | None = None,
            host_bucket: str | None = None,
            collection: str = "",
            service_name: str = "s3",
            logger: logging.Logger | None = None,
            region_name: str | None = None,
    ):
        # Bucket validation
        if not host_bucket:
            raise S3BucketNotSpecified()

        super().__init__(collection=collection, logger=logger)
        self._bucket = host_bucket

        # Parameter or env variable
        aws_access_key_id = access_key or os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = secret_key or os.getenv("AWS_SECRET_ACCESS_KEY")

        if not aws_access_key_id or not aws_secret_access_key:
            raise S3Error("AWS Access Key and Secret Key must be provided via arguments or environment variables.")

        # Client configuration
        config = Config(
            retries={
                'max_attempts': 5,
                'mode': 'adaptive'
            },
            connect_timeout=5,
            read_timeout=10
        )

        endpoint_url = s3_host or os.getenv("AWS_S3_ENDPOINT_URL")

        try:
            self._s3_client = boto3.client(
                service_name=service_name,
                endpoint_url=endpoint_url,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=region_name,
                config=config
            )

        except Exception as e:
            raise S3Error(f"Failed to initialize S3 client: {e}")

    # ---------------- LOW-LEVEL IMPLEMENTATION ----------------
    def _upload(self, remote_file_path: str, local_file_path: Path | str):
        local_file_path = str(local_file_path)
        self._logger.info(f"Uploading '{local_file_path}' to S3 key '{remote_file_path}'")
        self._s3_client.upload_file(local_file_path, self._bucket, remote_file_path)

    def _upload_atomic(self, remote_file_path: str, local_file_path: Path | str) -> None:
        """
        Atomically uploads a file to S3 storage with the condition 'IfNoneMatch: *'.

        :raises StorageFileAlreadyExists: If the file already exists in S3.
        """
        local_file_path = str(local_file_path)
        self._logger.debug(f"Attempting atomic upload for '{remote_file_path}'")

        try:
            self._s3_client.upload_file(
                local_file_path,
                self._bucket,
                remote_file_path,
                ExtraArgs={
                    'IfNoneMatch': '*',  # Condition: fails if object exists
                    'Metadata': {'created-by': 'atomic-lock'}  # Optional metadata
                }
            )

        except botocore.exceptions.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')

            if error_code == 'PreconditionFailed':
                # 412 Precondition Failed - file already exists
                raise StorageFileAlreadyExists(file=remote_file_path)

            elif error_code in ['403', 'AccessDenied']:
                raise PermissionError(f"Access denied while uploading {remote_file_path}")

            else:
                # Other errors like network issues, etc.
                raise e

        self._logger.info(f"Atomic upload successful for '{remote_file_path}'")

    def _download(self, remote_file_path: str, local_file_path: Path | str):
        local_file_path = str(local_file_path)
        self._logger.info(f"Downloading S3 key '{remote_file_path}' to '{local_file_path}'")
        if not self._exists(remote_file_path):
            raise StorageFileNotFoundError(file=remote_file_path)
        with open(local_file_path, "wb") as f:
            self._s3_client.download_fileobj(self._bucket, remote_file_path, f)

    def _delete(self, remote_file_path: str):
        self._logger.info(f"Deleting S3 key '{remote_file_path}'")
        self._s3_client.delete_object(Bucket=self._bucket, Key=remote_file_path)

    def _exists(self, remote_file_path: str, expected_length: int | None = None) -> bool:
        try:
            head = self._s3_client.head_object(Bucket=self._bucket, Key=remote_file_path)
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

        if expected_length is None:
            return True

        try:
            expected_length = int(expected_length)
        except (TypeError, ValueError):
            self._logger.warning(f"Invalid expected_length: {expected_length!r}")
            return False

        actual_length = int(head["ContentLength"])
        if actual_length != expected_length:
            self._logger.warning(f"S3 key '{remote_file_path}' length mismatch ({actual_length} != {expected_length})")
            return False

        return True
