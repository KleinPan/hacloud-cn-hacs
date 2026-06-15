"""HA Cloud CN 后端 API 客户端（基于 aiohttp）。"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    API_BIND,
    API_HEARTBEAT_TEMPLATE,
    API_NOTIFY_PUSH,
    API_SUBSCRIPTION_CURRENT,
    API_TRAFFIC_SUMMARY,
    HEADER_HA_TOKEN,
    INTEGRATION_VERSION,
)

_LOGGER = logging.getLogger(__name__)


class HaCloudApiError(Exception):
    """API 调用异常。"""


class HaCloudApiClient:
    """与 HaCloud.WebApi 交互的极简客户端。

    - 用户登录用的 JWT **不在这里管**。本地集成只持有 endpoint 的长期 token（绑定时拿到）
    - 所有 GET/POST 都不抛 4xx，只在 5xx / 网络错误时抛 HaCloudApiError
    """

    def __init__(
        self,
        backend_url: str,
        endpoint_id: int,
        token: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._backend_url = backend_url.rstrip("/")
        self._endpoint_id = endpoint_id
        self._token = token
        self._session = session

    @property
    def endpoint_id(self) -> int:
        return self._endpoint_id

    @property
    def backend_url(self) -> str:
        return self._backend_url

    @staticmethod
    async def bind(
        backend_url: str,
        bind_code: str,
        session: aiohttp.ClientSession,
        version: str = INTEGRATION_VERSION,
    ) -> dict:
        url = f"{backend_url.rstrip('/')}{API_BIND}"
        payload = {"bindCode": bind_code, "version": version}
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 405:
                    raise HaCloudApiError(
                        "bind 失败 HTTP 405 — 反向代理未正确配置，"
                        "/prod-api/* 请求未转发到后端 API，请检查 Caddy/Nginx 配置"
                    )
                if resp.status != 200:
                    try:
                        body = await resp.json()
                        msg = body.get("msg") or f"bind 失败 HTTP {resp.status}"
                    except Exception:
                        msg = f"bind 失败 HTTP {resp.status}"
                    raise HaCloudApiError(msg)
                data = await resp.json()
                if data.get("code") != 200 or not data.get("data"):
                    raise HaCloudApiError(data.get("msg") or "接入码无效或已过期")
                return data["data"]
        except HaCloudApiError:
            raise
        except aiohttp.ClientError as err:
            raise HaCloudApiError(f"网络错误：{err}") from err

    async def heartbeat(self, system_info: dict | None = None) -> dict:
        url = self._abs(API_HEARTBEAT_TEMPLATE.format(endpoint_id=self._endpoint_id))
        payload: dict[str, Any] = {"version": INTEGRATION_VERSION}
        if system_info:
            payload["systemInfo"] = system_info
        return await self._post(url, payload)

    async def get_current_subscription(self) -> dict | None:
        url = self._abs(API_SUBSCRIPTION_CURRENT)
        try:
            return await self._get(url)
        except HaCloudApiError as err:
            _LOGGER.debug("subscription/current 暂不可用：%s", err)
            return None

    async def get_traffic_summary(self) -> dict | None:
        url = self._abs(API_TRAFFIC_SUMMARY)
        try:
            return await self._get(url)
        except HaCloudApiError as err:
            _LOGGER.debug("traffic/summary 暂不可用：%s", err)
            return None

    async def notify_push(self, title: str, message: str) -> dict:
        url = self._abs(API_NOTIFY_PUSH)
        payload = {"title": title, "message": message}
        return await self._post(url, payload)

    def _abs(self, path: str) -> str:
        return f"{self._backend_url}{path}"

    def _headers(self) -> dict[str, str]:
        return {HEADER_HA_TOKEN: self._token, "Content-Type": "application/json"}

    async def _post(self, url: str, payload: dict[str, Any]) -> dict:
        try:
            async with self._session.post(
                url, json=payload, headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status >= 500:
                    raise HaCloudApiError(f"server error {resp.status}")
                data = await resp.json()
                return data.get("data") or {}
        except aiohttp.ClientError as err:
            raise HaCloudApiError(str(err)) from err

    async def _get(self, url: str) -> dict:
        try:
            async with self._session.get(
                url, headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status >= 500:
                    raise HaCloudApiError(f"server error {resp.status}")
                data = await resp.json()
                return data.get("data") or {}
        except aiohttp.ClientError as err:
            raise HaCloudApiError(str(err)) from err
