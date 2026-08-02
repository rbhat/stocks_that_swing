"""Narrow HTTP client for the isolated legacy admin sidecar."""

from __future__ import annotations

from typing import Any

import httpx


class RunnerUnavailable(RuntimeError):
    pass


def _request(
    method: str,
    path: str,
    *,
    base_url: str | None,
    token: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not base_url or not token:
        raise RunnerUnavailable("legacy admin runner is not configured")
    try:
        response = httpx.request(
            method,
            f"{base_url.rstrip('/')}{path}",
            headers={"X-Legacy-Admin-Token": token},
            json=payload,
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise RunnerUnavailable("legacy admin runner is unavailable") from exc
    if response.status_code == 409:
        raise FileExistsError("legacy sync already running")
    if response.status_code == 404:
        raise KeyError(path)
    if response.status_code == 422:
        detail = response.json().get("detail", [])
        raise ValueError(detail)
    if response.status_code in {401, 403}:
        raise RunnerUnavailable("legacy admin runner rejected its credentials")
    if response.status_code >= 500:
        raise RunnerUnavailable("legacy admin runner failed")
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RunnerUnavailable("legacy admin runner returned an invalid response")
    return value


def start_sync(base_url: str | None, token: str | None) -> dict[str, Any]:
    return _request("POST", "/sync", base_url=base_url, token=token)


def sync_state(base_url: str | None, token: str | None, sync_id: str) -> dict[str, Any]:
    return _request("GET", f"/sync/{sync_id}", base_url=base_url, token=token)


def update_config(
    base_url: str | None, token: str | None, updates: dict[str, Any]
) -> dict[str, Any]:
    return _request("PUT", "/config", base_url=base_url, token=token, payload=updates)
