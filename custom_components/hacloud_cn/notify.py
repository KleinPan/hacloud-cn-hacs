"""Notify 平台：将 HA 自动化告警转发到 HA Cloud 用户配置的通知渠道。

用户在 HA Cloud 后台配好通知渠道（企业微信/Telegram/钉钉/邮件/Webhook）后，
在 HA 自动化中调用 notify.hacloud_cn 即可将告警推送到这些渠道。

使用示例：
  service: notify.hacloud_cn
  data:
    title: "⚠️ 漏水检测"
    message: "厨房漏水传感器触发，请立即检查！"
"""
from __future__ import annotations

import logging

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import HaCloudApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: HaCloudApiClient = entry_data["client"]
    async_add_entities([HaCloudNotifyEntity(client)])


class HaCloudNotifyEntity(NotifyEntity):
    """HA Cloud CN 通知服务 — 将 HA 告警转发到云端用户配置的通知渠道。"""

    _attr_name = "HA Cloud"

    def __init__(self, client: HaCloudApiClient) -> None:
        self._client = client

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        try:
            await self._client.notify_push(
                title=title or "Home Assistant",
                message=message,
            )
        except Exception as err:
            _LOGGER.error("HA Cloud 通知推送失败: %s", err)
