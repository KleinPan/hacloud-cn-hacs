"""Config flow：极简两步配置 — 输入接入码 → 自动绑定并启动 frpc。"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HaCloudApiClient, HaCloudApiError
from .const import (
    CONF_BACKEND_URL,
    CONF_BIND_CODE,
    CONF_ENDPOINT_ID,
    CONF_FRP_PORT,
    CONF_FRPC_ENABLED,
    CONF_FRPS_ADDR,
    CONF_FRPS_AUTH_TOKEN,
    CONF_FULL_DOMAIN,
    CONF_SUBDOMAIN,
    CONF_TOKEN,
    DOMAIN,
    FRPC_VERSION,
)
from .frpc_manager import resolve_frpc_binary

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BACKEND_URL, default="https://hacloud.asia"): str,
        vol.Required(CONF_BIND_CODE): str,
    }
)


class HaCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """处理 HA Cloud CN 集成的配置流程。"""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._bind_result: dict | None = None
        self._backend_url: str = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """第一步：填后端 URL + 接入码。"""
        errors: dict[str, str] = {}
        if user_input is not None:
            backend_url = user_input[CONF_BACKEND_URL]
            bind_code = user_input[CONF_BIND_CODE]
            session = async_get_clientsession(self.hass)
            try:
                result = await HaCloudApiClient.bind(backend_url, bind_code, session)
            except HaCloudApiError as err:
                _LOGGER.warning("bind 失败：%s", err)
                err_msg = str(err)
                if "405" in err_msg:
                    errors["base"] = "proxy_misconfigured"
                else:
                    errors["base"] = "bind_failed"
            else:
                endpoint_id = result.get("endpointId")
                token = result.get("token")
                subdomain = result.get("subdomain")
                frps_addr = result.get("frpsAddr")
                full_domain = result.get("fullDomain")
                frp_port = result.get("frpPort")
                frps_auth_token = result.get("frpsAuthToken") or ""
                if not (endpoint_id and token):
                    errors["base"] = "bind_failed"
                else:
                    self._bind_result = {
                        CONF_BACKEND_URL: backend_url,
                        CONF_ENDPOINT_ID: endpoint_id,
                        CONF_TOKEN: token,
                        CONF_SUBDOMAIN: subdomain,
                        CONF_FRPS_ADDR: frps_addr,
                        CONF_FULL_DOMAIN: full_domain,
                        CONF_FRP_PORT: frp_port,
                        CONF_FRPS_AUTH_TOKEN: frps_auth_token,
                    }
                    self._backend_url = backend_url
                    return await self.async_step_frpc()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_frpc(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """第二步：确认 frpc 状态，完成配置。"""
        if user_input is not None:
            frpc_enabled = user_input.get(CONF_FRPC_ENABLED, True)
            self._bind_result[CONF_FRPC_ENABLED] = frpc_enabled

            endpoint_id = self._bind_result[CONF_ENDPOINT_ID]
            subdomain = self._bind_result.get(CONF_SUBDOMAIN, "")
            full_domain = self._bind_result.get(CONF_FULL_DOMAIN) or subdomain

            await self.async_set_unique_id(str(endpoint_id))
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"HA Cloud · {full_domain}",
                data=self._bind_result,
            )

        frpc_binary = resolve_frpc_binary(self.hass)
        frpc_found = frpc_binary is not None

        schema = vol.Schema({
            vol.Required(CONF_FRPC_ENABLED, default=True): bool,
        })

        frpc_hint = f"✅ 已检测到 frpc：{frpc_binary}\n绑定完成后将自动启动隧道。" if frpc_found else (
            f"ℹ️ 未检测到 frpc，完成配置后将自动从 GitHub 下载 frpc v{FRPC_VERSION}，无需手动安装。\n"
            "你也可以先关闭 frpc 自动管理，稍后手动处理。"
        )

        return self.async_show_form(
            step_id="frpc",
            data_schema=schema,
            description_placeholders={"frpc_hint": frpc_hint},
        )
