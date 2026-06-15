"""HA Cloud CN — 国内 Home Assistant 云服务的 HACS 集成包。

v0.2: 新增 frpc 自动配置与进程管理。
绑定成功后自动生成 frpc.toml 并启动 frpc 进程，
用户无需手动配置任何隧道参数。
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.system_info import async_get_system_info
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import HaCloudApiClient
from .const import (
    CONF_BACKEND_URL,
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
    INTEGRATION_VERSION,
    UPDATE_INTERVAL_SECONDS,
)
from .frpc_manager import (
    FrpcManager,
    download_and_install_frpc,
    generate_frpc_config,
    resolve_frpc_binary,
    write_frpc_config,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NOTIFY]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA Cloud CN from a config entry."""
    _LOGGER.info("HA Cloud CN v%s 正在初始化 (entry_id=%s)", INTEGRATION_VERSION, entry.entry_id)
    session = async_get_clientsession(hass)
    client = HaCloudApiClient(
        backend_url=entry.data[CONF_BACKEND_URL],
        endpoint_id=entry.data[CONF_ENDPOINT_ID],
        token=entry.data[CONF_TOKEN],
        session=session,
    )

    frpc_manager = FrpcManager(hass)

    frpc_enabled = entry.data.get(CONF_FRPC_ENABLED, True)
    if frpc_enabled:
        frps_addr = entry.data.get(CONF_FRPS_ADDR, "")
        token = entry.data.get(CONF_TOKEN, "")
        subdomain = entry.data.get(CONF_SUBDOMAIN, "")
        frp_port = entry.data.get(CONF_FRP_PORT, 0)
        frps_auth_token = entry.data.get(CONF_FRPS_AUTH_TOKEN, "")

        if not frps_auth_token:
            _LOGGER.warning(
                "frps_auth_token 为空，frpc 可能无法通过 frps 的 token 认证。"
                "如果您的集成配置是在早期版本创建的，请删除并重新添加集成以获取 frps_auth_token"
            )
        else:
            _LOGGER.info(
                "config entry 中 frps_auth_token: len=%d raw=%r hex=%s",
                len(frps_auth_token),
                frps_auth_token,
                ' '.join(f'{b:02x}' for b in frps_auth_token.encode('utf-8')),
            )

        if frps_addr and token and subdomain and frp_port:
            config_content = generate_frpc_config(
                frps_addr, token, subdomain, frp_port,
                frps_auth_token=frps_auth_token,
            )
            await write_frpc_config(hass, config_content)

            binary = resolve_frpc_binary(hass)
            if binary:
                started = await frpc_manager.start(binary)
                if started:
                    _LOGGER.info("frpc 自动启动成功，终端 %s 隧道已建立", subdomain)
                else:
                    _LOGGER.warning("frpc 自动启动失败，请检查 frpc 安装和配置")
            else:
                _LOGGER.info("未找到 frpc，尝试自动下载 v%s...", FRPC_VERSION)
                binary = await download_and_install_frpc(hass, session)
                if binary:
                    started = await frpc_manager.start(binary)
                    if started:
                        _LOGGER.info("frpc 下载并启动成功，终端 %s 隧道已建立", subdomain)
                    else:
                        _LOGGER.warning("frpc 下载成功但启动失败，请检查配置")
                else:
                    _LOGGER.warning(
                        "未找到 frpc 且自动下载失败。详细的手动安装步骤请查看上方 ERROR 级日志，"
                        "或将 frpc 二进制文件放到 %s/ 目录后重新加载集成",
                        hass.config.config_dir + "/hacloud_cn",
                    )

    system_info = {}
    try:
        sys_info = await async_get_system_info(hass)
        system_info = {
            "haVersion": sys_info.get("version"),
            "installationType": sys_info.get("installation_type"),
            "arch": sys_info.get("arch"),
            "osName": sys_info.get("os_name"),
            "osVersion": sys_info.get("os_version"),
            "docker": sys_info.get("docker"),
            "hassio": sys_info.get("hassio"),
        }
        if sys_info.get("hassio"):
            system_info["chassis"] = sys_info.get("chassis")
            system_info["hostOs"] = sys_info.get("host_os")
            system_info["supervisor"] = sys_info.get("supervisor")
    except Exception:
        _LOGGER.debug("系统信息采集失败，心跳将不携带系统信息")

    coordinator = HaCloudCoordinator(hass, client, frpc_manager, system_info)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "frpc_manager": frpc_manager,
        "client": client,
        "system_info": system_info,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    frpc_manager: FrpcManager | None = entry_data.get("frpc_manager")
    if frpc_manager:
        await frpc_manager.stop()
        _LOGGER.info("frpc 已随集成卸载而停止")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


class HaCloudCoordinator(DataUpdateCoordinator[dict]):
    """单一协调器，聚合 heartbeat / subscription / traffic 三个调用，
    并在每次更新时确保 frpc 进程存活。"""

    def __init__(
        self,
        hass: HomeAssistant,
        client: HaCloudApiClient,
        frpc_manager: FrpcManager,
        system_info: dict | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.client = client
        self._frpc_manager = frpc_manager
        self._system_info = system_info or {}

    async def _async_update_data(self) -> dict:
        """周期拉取：先 heartbeat 上报在线，再拉订阅 + 流量摘要，最后确保 frpc 存活。"""
        try:
            await self.client.heartbeat(self._system_info)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Heartbeat failed: %s", err)

        subscription = await self.client.get_current_subscription()
        traffic = await self.client.get_traffic_summary()

        if traffic:
            for key in ("totalBytesMonth", "upBytesMonth", "downBytesMonth"):
                val = traffic.get(key)
                if val is not None:
                    try:
                        traffic[key] = float(val)
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            "v%s 流量字段 %s 转换失败: val=%r type=%s",
                            INTEGRATION_VERSION, key, val, type(val).__name__,
                        )
                        traffic[key] = None

        frpc_status = self._frpc_manager.status
        frpc_version = self._frpc_manager.version
        if self._system_info:
            self._system_info["frpcVersion"] = frpc_version
            self._system_info["frpcStatus"] = frpc_status
        if not self._frpc_manager.is_running:
            _LOGGER.debug("frpc 未运行，尝试恢复...")
            await self._frpc_manager.ensure_running()

        return {
            "online": True,
            "subscription": subscription,
            "traffic": traffic,
            "frpc_status": frpc_status,
        }
