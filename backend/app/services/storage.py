import logging
from pathlib import Path
from typing import NoReturn
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class DatasetStorageError(RuntimeError):
    pass


def _object_url(stored_name: str) -> str:
    bucket = quote(settings.supabase_storage_bucket, safe="")
    object_name = quote(stored_name, safe="")
    return (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{bucket}/{object_name}"
    )


def _headers(content_type: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def storage_readiness() -> dict[str, str | bool]:
    if settings.data_storage_backend == "local":
        return {
            "backend": "local",
            "status": "local",
            "persistent": False,
            "private": True,
            "message": (
                "Local files are private to this service but are not guaranteed to "
                "survive a hosted-instance restart. Configure persistent object storage."
            ),
        }

    bucket_url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/bucket/"
        f"{quote(settings.supabase_storage_bucket, safe='')}"
    )
    try:
        with httpx.Client(timeout=3) as client:
            response = client.get(bucket_url, headers=_headers())
    except httpx.HTTPError as error:
        logger.warning(
            "Dataset storage readiness check failed backend=supabase exception=%s",
            type(error).__name__,
        )
        return {
            "backend": "supabase",
            "status": "unavailable",
            "persistent": True,
            "private": False,
            "message": "Supabase Storage could not be reached.",
        }

    if response.status_code == 404:
        status_value = "bucket_missing"
        message = "The configured Supabase Storage bucket was not found."
    elif response.status_code in {401, 403}:
        status_value = "access_denied"
        message = "Supabase Storage rejected the configured server credentials."
    elif response.status_code != 200:
        status_value = "unavailable"
        message = "Supabase Storage is unavailable."
    else:
        try:
            bucket = response.json()
        except ValueError:
            bucket = None
        if not isinstance(bucket, dict) or not isinstance(bucket.get("public"), bool):
            status_value = "visibility_unverified"
            message = "The Supabase bucket visibility could not be verified."
        elif bucket["public"]:
            status_value = "bucket_public"
            message = "The configured Supabase bucket is public; use a private bucket."
        else:
            status_value = "ready"
            message = "The configured Supabase bucket is reachable and private."

    return {
        "backend": "supabase",
        "status": status_value,
        "persistent": True,
        "private": status_value == "ready",
        "message": message,
    }


def _raise_cloud_error(operation: str, error: httpx.HTTPError) -> NoReturn:
    status_code = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
    logger.warning(
        "Dataset storage request failed backend=supabase operation=%s exception=%s http_status=%s",
        operation,
        type(error).__name__,
        status_code,
    )
    raise DatasetStorageError("Cloud dataset storage is unavailable or misconfigured.") from error


def save_dataset(stored_name: str, content: bytes, local_path: Path) -> None:
    if settings.data_storage_backend == "local":
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)
        return

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                _object_url(stored_name),
                content=content,
                headers={
                    **_headers("application/octet-stream"),
                    "x-upsert": "false",
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as error:
        _raise_cloud_error("upload", error)


def read_dataset(stored_name: str, local_path: Path) -> bytes:
    if settings.data_storage_backend == "local":
        return local_path.read_bytes()

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(_object_url(stored_name), headers=_headers())
            if response.status_code == 404:
                raise FileNotFoundError(stored_name)
            response.raise_for_status()
            return response.content
    except httpx.HTTPStatusError as error:
        _raise_cloud_error("download", error)
    except httpx.HTTPError as error:
        _raise_cloud_error("download", error)


def delete_dataset(stored_name: str, local_path: Path) -> None:
    if settings.data_storage_backend == "local":
        local_path.unlink(missing_ok=True)
        return

    bucket_url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{quote(settings.supabase_storage_bucket, safe='')}"
    )
    try:
        with httpx.Client(timeout=30) as client:
            response = client.request(
                "DELETE",
                bucket_url,
                json={"prefixes": [stored_name]},
                headers=_headers(),
            )
            if response.status_code == 404:
                return
            response.raise_for_status()
    except httpx.HTTPError as error:
        _raise_cloud_error("delete", error)
