"""常量定义。"""
from __future__ import annotations

import json
from pathlib import Path

DOMAIN = "hacloud_cn"
_MANIFEST = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
INTEGRATION_VERSION: str = _MANIFEST["version"]

CONF_BACKEND_URL = "backend_url"
CONF_BIND_CODE = "bind_code"
CONF_ENDPOINT_ID = "endpoint_id"
CONF_TOKEN = "token"
CONF_SUBDOMAIN = "subdomain"
CONF_FRPS_ADDR = "frps_addr"
CONF_FULL_DOMAIN = "full_domain"
CONF_FRP_PORT = "frp_port"
CONF_FRPC_ENABLED = "frpc_enabled"
CONF_FRPS_AUTH_TOKEN = "frps_auth_token"

UPDATE_INTERVAL_SECONDS = 60

API_PREFIX = "/prod-api"
API_BIND = "/prod-api/hacloud/endpoint/bind"
API_HEARTBEAT_TEMPLATE = "/prod-api/hacloud/endpoint/{endpoint_id}/heartbeat"
API_SUBSCRIPTION_CURRENT = "/prod-api/hacloud/subscription/current"
API_TRAFFIC_SUMMARY = "/prod-api/hacloud/traffic/summary"
API_NOTIFY_PUSH = "/prod-api/hacloud/notify/push"

HEADER_HA_TOKEN = "X-HA-Token"

SENSOR_ONLINE = "online"
SENSOR_SUBSCRIPTION_EXPIRES = "subscription_expires"
SENSOR_TRAFFIC_MONTH_MB = "traffic_month_mb"

FRPC_VERSION = "0.61.1"
FRPC_BINARY_NAME = "frpc"
FRPC_CONFIG_DIR = "hacloud_cn"
FRPC_CONFIG_FILENAME = "frpc.toml"
FRPC_LOG_FILENAME = "frpc.log"
FRPC_RESTART_DELAY = 5
FRPC_MAX_RESTARTS = 5
FRPC_WATCHDOG_INTERVAL = 30
