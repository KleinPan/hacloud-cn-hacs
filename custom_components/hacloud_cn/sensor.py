"""Sensor 实体：在线状态、本月流量、订阅到期日、域名信息、frpc 隧道状态。"""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENDPOINT_ID,
    CONF_FRP_PORT,
    CONF_FRPS_ADDR,
    CONF_FULL_DOMAIN,
    CONF_SUBDOMAIN,
    DOMAIN,
    INTEGRATION_VERSION,
    SENSOR_ONLINE,
    SENSOR_SUBSCRIPTION_EXPIRES,
    SENSOR_TRAFFIC_MONTH_MB,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """配置 entry 时挂载 sensor。"""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    endpoint_id = entry.data[CONF_ENDPOINT_ID]
    subdomain = entry.data.get(CONF_SUBDOMAIN) or str(endpoint_id)
    full_domain = entry.data.get(CONF_FULL_DOMAIN) or f"{subdomain}.hacloud.asia"
    frps_addr = entry.data.get(CONF_FRPS_ADDR)
    frp_port = entry.data.get(CONF_FRP_PORT)
    async_add_entities(
        [
            HaCloudOnlineSensor(coordinator, endpoint_id, subdomain),
            HaCloudTrafficMonthSensor(coordinator, endpoint_id, subdomain),
            HaCloudSubscriptionExpiresSensor(coordinator, endpoint_id, subdomain),
            HaCloudDomainInfoSensor(coordinator, endpoint_id, subdomain, full_domain, frps_addr, frp_port),
            HaCloudFrpcStatusSensor(coordinator, endpoint_id, subdomain),
        ]
    )


class _BaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, endpoint_id: int, subdomain: str, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._endpoint_id = endpoint_id
        self._subdomain = subdomain
        self._attr_unique_id = f"hacloud_cn_{endpoint_id}_{key}"
        self._attr_name = name


class HaCloudOnlineSensor(_BaseSensor):
    _attr_icon = "mdi:cloud-check-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, endpoint_id: int, subdomain: str) -> None:
        super().__init__(coordinator, endpoint_id, subdomain, SENSOR_ONLINE, "在线状态")

    @property
    def native_value(self) -> str:
        return "在线" if self.coordinator.data.get("online") else "离线"


class HaCloudTrafficMonthSensor(_BaseSensor):
    _attr_icon = "mdi:chart-line"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, endpoint_id: int, subdomain: str) -> None:
        super().__init__(coordinator, endpoint_id, subdomain, SENSOR_TRAFFIC_MONTH_MB, "本月流量")

    @property
    def native_value(self) -> float | None:
        traffic = (self.coordinator.data or {}).get("traffic") or {}
        total_bytes = traffic.get("totalBytesMonth")
        if total_bytes is None:
            return None
        try:
            return round(float(total_bytes) / 1024 / 1024, 2)
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "v%s 本月流量转换失败: totalBytesMonth=%r type=%s err=%s",
                INTEGRATION_VERSION, total_bytes, type(total_bytes).__name__, err,
            )
            return None


class HaCloudSubscriptionExpiresSensor(_BaseSensor):
    _attr_icon = "mdi:calendar-end"

    def __init__(self, coordinator, endpoint_id: int, subdomain: str) -> None:
        super().__init__(coordinator, endpoint_id, subdomain, SENSOR_SUBSCRIPTION_EXPIRES, "订阅到期")

    @property
    def native_value(self) -> str | None:
        sub = (self.coordinator.data or {}).get("subscription") or {}
        end_at = sub.get("endAt")
        if not end_at:
            return "无订阅"
        try:
            return datetime.fromisoformat(end_at.replace(" ", "T")).date().isoformat()
        except Exception:  # noqa: BLE001
            return str(end_at)[:10]


class HaCloudDomainInfoSensor(_BaseSensor):
    _attr_icon = "mdi:web"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator,
        endpoint_id: int,
        subdomain: str,
        full_domain: str,
        frps_addr: str | None,
        frp_port: int | None,
    ) -> None:
        super().__init__(coordinator, endpoint_id, subdomain, "domain_info", "域名信息")
        self._full_domain = full_domain
        self._frps_addr = frps_addr
        self._frp_port = frp_port

    @property
    def native_value(self) -> str:
        return self._full_domain

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "full_domain": self._full_domain,
            "subdomain": self._subdomain,
        }
        if self._frps_addr:
            attrs["frps_addr"] = self._frps_addr
        if self._frp_port:
            attrs["frp_port"] = self._frp_port
        return attrs


class HaCloudFrpcStatusSensor(_BaseSensor):
    _attr_icon = "mdi:tunnel"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, endpoint_id: int, subdomain: str) -> None:
        super().__init__(coordinator, endpoint_id, subdomain, "frpc_status", "隧道状态")

    @property
    def native_value(self) -> str:
        status = (self.coordinator.data or {}).get("frpc_status", "unknown")
        status_map = {
            "running": "运行中",
            "stopped": "已停止",
        }
        if status in status_map:
            return status_map[status]
        if status.startswith("exited"):
            return f"已退出{status[6:]}"
        return status

    @property
    def extra_state_attributes(self) -> dict:
        status = (self.coordinator.data or {}).get("frpc_status", "unknown")
        return {"raw_status": status}
