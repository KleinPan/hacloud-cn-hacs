"""frpc 进程管理器：生成配置、启动/停止/重启 frpc 原生进程。"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import platform
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant

from .const import (
    FRPC_BINARY_NAME,
    FRPC_CONFIG_DIR,
    FRPC_CONFIG_FILENAME,
    FRPC_LOG_FILENAME,
    FRPC_MAX_RESTARTS,
    FRPC_RESTART_DELAY,
    FRPC_VERSION,
    FRPC_WATCHDOG_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_VER = FRPC_VERSION
_GH_PATH = f"github.com/fatedier/frp/releases/download/v{_VER}"

_ARCH_MAP: dict[str, str] = {
    "aarch64": f"frp_{_VER}_linux_arm64.tar.gz",
    "armv7l": f"frp_{_VER}_linux_arm.tar.gz",
    "x86_64": f"frp_{_VER}_linux_amd64.tar.gz",
    "amd64": f"frp_{_VER}_linux_amd64.tar.gz",
}

_MIRROR_PREFIXES: list[tuple[str, str]] = [
    ("ghfast.top", f"https://ghfast.top/https://{_GH_PATH}"),
    ("gh-proxy.com", f"https://gh-proxy.com/https://{_GH_PATH}"),
    ("ghproxy.vip", f"https://ghproxy.vip/https://{_GH_PATH}"),
    ("gh.ddlc.top", f"https://gh.ddlc.top/https://{_GH_PATH}"),
    ("GitHub", f"https://{_GH_PATH}"),
]

FRPC_DOWNLOAD_MIRRORS: list[dict[str, str]] = [
    {
        "name": name,
        "urls": {arch: f"{base}/{filename}" for arch, filename in _ARCH_MAP.items()},
    }
    for name, base in _MIRROR_PREFIXES
]


def _config_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.config_dir) / FRPC_CONFIG_DIR


def _config_path(hass: HomeAssistant) -> Path:
    return _config_dir(hass) / FRPC_CONFIG_FILENAME


def _log_path(hass: HomeAssistant) -> Path:
    return _config_dir(hass) / FRPC_LOG_FILENAME


def _frpc_binary_path(hass: HomeAssistant) -> Path:
    return _config_dir(hass) / FRPC_BINARY_NAME


def find_system_frpc() -> str | None:
    return shutil.which(FRPC_BINARY_NAME)


def find_local_frpc(hass: HomeAssistant) -> str | None:
    local = _frpc_binary_path(hass)
    if local.exists() and os.access(str(local), os.X_OK):
        return str(local)
    return None


def resolve_frpc_binary(hass: HomeAssistant) -> str | None:
    return find_local_frpc(hass) or find_system_frpc()


def _hex_dump(s: str) -> str:
    """Return hex dump of a string's UTF-8 bytes for audit."""
    return ' '.join(f'{b:02x}' for b in s.encode('utf-8'))


def generate_frpc_config(
    frps_addr: str,
    token: str,
    subdomain: str,
    frp_port: int,
    ha_port: int = 8123,
    frps_auth_token: str = "",
) -> str:
    host, _, port_str = frps_addr.partition(":")
    port = int(port_str) if port_str else 7000
    auth_section = ""
    if frps_auth_token:
        _LOGGER.info(
            "frpc auth.token 写入: len=%d raw=%r hex=%s",
            len(frps_auth_token),
            frps_auth_token,
            _hex_dump(frps_auth_token),
        )
        auth_section = f"""
[auth]
method = "token"
token = "{frps_auth_token}"
"""
    else:
        _LOGGER.warning("frpc auth.token 为空！frps 可能已启用 auth.token 要求，frpc 将无法通过认证")
    _LOGGER.info(
        "frpc metadatas.token 写入: len=%d raw=%r hex=%s",
        len(token),
        token,
        _hex_dump(token),
    )
    return f"""serverAddr = "{host}"
serverPort = {port}
loginFailExit = false
metadatas.token = "{token}"
{auth_section}
[[proxies]]
name = "{subdomain}"
type = "tcp"
localIP = "127.0.0.1"
localPort = {ha_port}
remotePort = {frp_port}
metadatas.token = "{token}"

[transport]
tcpMux = true
tcpMuxKeepaliveInterval = 15
heartbeatInterval = 15
heartbeatTimeout = 60
[transport.tls]
enable = false

[log]
to = ""
level = "info"
maxDays = 7
"""


async def write_frpc_config(hass: HomeAssistant, config_content: str) -> Path:
    config_dir = _config_dir(hass)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = _config_path(hass)
    await asyncio.get_event_loop().run_in_executor(
        None, config_path.write_text, config_content, "utf-8"
    )
    _LOGGER.info("frpc 配置已写入: %s", config_path)
    return config_path


async def download_and_install_frpc(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
) -> str | None:
    arch = platform.machine()
    filename = _ARCH_MAP.get(arch)
    if not filename:
        _LOGGER.error(
            "不支持的 CPU 架构: %s。请手动下载 frpc 二进制文件，"
            "并将其放置到 %s/%s（确保可执行权限：chmod +x）",
            arch,
            _config_dir(hass),
            FRPC_BINARY_NAME,
        )
        return None

    target_dir = _config_dir(hass)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_binary = _frpc_binary_path(hass)

    if target_binary.exists() and os.access(str(target_binary), os.X_OK):
        return str(target_binary)

    tried_urls: list[str] = []
    tar_data: bytes | None = None
    for mirror in FRPC_DOWNLOAD_MIRRORS:
        mirror_url = mirror["urls"].get(arch)
        if not mirror_url:
            continue
        mirror_name = mirror["name"]
        tried_urls.append(mirror_url)
        _LOGGER.info("正在从 %s 下载 frpc v%s (%s)...", mirror_name, FRPC_VERSION, arch)
        _LOGGER.info("下载地址: %s", mirror_url)
        try:
            async with session.get(mirror_url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 200:
                    tar_data = await resp.read()
                    _LOGGER.info("从 %s 下载 frpc 成功 (%d bytes)", mirror_name, len(tar_data))
                    break
                _LOGGER.warning("从 %s 下载失败，HTTP %s", mirror_name, resp.status)
        except Exception as err:
            _LOGGER.warning("从 %s 下载失败: %s", mirror_name, err)

    if tar_data is None:
        urls_list = "\n  ".join(tried_urls)
        _LOGGER.error(
            "所有镜像源均下载 frpc 失败。请按以下步骤手动安装：\n"
            "  1. 当前系统架构: %s\n"
            "  2. 在能访问外网的机器上，从下面任一地址下载 frp 压缩包：\n"
            "  %s\n"
            "  3. 解压后将其中的 %s 文件复制到 HA 配置目录: %s\n"
            "  4. Linux/HAOS 下设置可执行权限: chmod +x %s\n"
            "  5. 在 HA 中重新加载本集成（或重启 HA）",
            arch,
            urls_list,
            FRPC_BINARY_NAME,
            target_binary,
            target_binary,
        )
        return None

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tar:
                tar.extractall(path=tmp_dir)

            for root, _dirs, files in os.walk(tmp_dir):
                if FRPC_BINARY_NAME in files:
                    src = Path(root) / FRPC_BINARY_NAME
                    shutil.copy2(str(src), str(target_binary))
                    try:
                        st = os.stat(str(target_binary))
                        os.chmod(
                            str(target_binary),
                            st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH,
                        )
                    except OSError:
                        pass
                    _LOGGER.info("frpc 已下载并安装到: %s", target_binary)
                    return str(target_binary)

            _LOGGER.error("下载的压缩包中未找到 frpc 二进制文件")
            return None
    except Exception as err:
        _LOGGER.error("解压或安装 frpc 失败: %s", err)
        return None


class FrpcManager:
    """frpc 进程生命周期管理：启动、停止、重启、watchdog。"""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._process: asyncio.subprocess.Process | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._restart_count = 0
        self._running = False
        self._binary: str | None = None
        self._config_path: Path | None = None
        self._frpc_version: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running and self._process is not None and self._process.returncode is None

    @property
    def status(self) -> str:
        if self.is_running:
            return "running"
        if self._process is not None and self._process.returncode is not None:
            return f"exited({self._process.returncode})"
        return "stopped"

    @property
    def version(self) -> str | None:
        return self._frpc_version

    async def start(self, binary: str | None = None) -> bool:
        if self.is_running:
            _LOGGER.warning("frpc 已在运行，跳过启动")
            return True

        self._binary = binary or resolve_frpc_binary(self._hass)
        if not self._binary:
            _LOGGER.error(
                "找不到 frpc 二进制文件。请安装 frpc 到系统 PATH 或 %s 目录",
                _config_dir(self._hass),
            )
            return False

        self._config_path = _config_path(self._hass)
        if not self._config_path.exists():
            _LOGGER.error("frpc 配置文件不存在: %s", self._config_path)
            return False

        _LOGGER.info("frpc 二进制路径: %s", self._binary)
        _LOGGER.info("frpc 配置路径: %s", self._config_path)

        try:
            _LOGGER.info("正在校验 frpc 配置: %s verify -c %s", self._binary, self._config_path)
            self._process = await asyncio.create_subprocess_exec(
                self._binary,
                "verify",
                "-c",
                str(self._config_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await self._process.wait()
            stdout, stderr = await self._process.stdout.read(), await self._process.stderr.read()
            stdout_text = stdout.decode(errors="replace").strip()
            stderr_text = stderr.decode(errors="replace").strip()

            if self._process.returncode != 0:
                _LOGGER.error(
                    "frpc 配置校验失败 (exit code=%s)\n  stdout: %s\n  stderr: %s",
                    self._process.returncode,
                    stdout_text or "(空)",
                    stderr_text or "(空)",
                )
                self._process = None
                return False

            _LOGGER.info("frpc 配置校验通过")
            if stdout_text:
                _LOGGER.debug("frpc verify stdout: %s", stdout_text)
            if stderr_text:
                _LOGGER.debug("frpc verify stderr: %s", stderr_text)
            try:
                ver_proc = await asyncio.create_subprocess_exec(
                    self._binary, "-v",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(ver_proc.wait(), timeout=5)
                if ver_proc.returncode == 0:
                    ver_out = (await ver_proc.stdout.read()).decode(errors="replace").strip()
                    self._frpc_version = ver_out or FRPC_VERSION
                else:
                    self._frpc_version = FRPC_VERSION
            except Exception:
                self._frpc_version = FRPC_VERSION
        except Exception as err:
            _LOGGER.error("frpc 配置校验异常: %s", type(err).__name__)
            _LOGGER.debug("frpc 配置校验异常详情", exc_info=err)
            return False

        try:
            log_path = _log_path(self._hass)
            _LOGGER.info("正在启动 frpc: %s -c %s", self._binary, self._config_path)
            self._process = await asyncio.create_subprocess_exec(
                self._binary,
                "-c",
                str(self._config_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._running = True
            self._restart_count = 0
            _LOGGER.info("frpc 已启动 (PID: %s)", self._process.pid)

            self._watchdog_task = asyncio.create_task(self._watchdog())
            return True
        except Exception as err:
            _LOGGER.error("frpc 启动失败: %s", type(err).__name__)
            _LOGGER.debug("frpc 启动失败详情", exc_info=err)
            self._process = None
            return False

    async def stop(self) -> None:
        self._running = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None

        if self._process and self._process.returncode is None:
            _LOGGER.info("正在停止 frpc (PID: %s)...", self._process.pid)
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                _LOGGER.warning("frpc 未在 10s 内退出，强制 kill")
                self._process.kill()
                await self._process.wait()
            _LOGGER.info("frpc 已停止")
        self._process = None

    async def restart(self) -> bool:
        await self.stop()
        await asyncio.sleep(1)
        return await self.start(self._binary)

    async def _watchdog(self) -> None:
        while self._running:
            await asyncio.sleep(FRPC_WATCHDOG_INTERVAL)
            if self._process is None or self._process.returncode is None:
                continue

            exit_code = self._process.returncode
            stdout_data = b""
            stderr_data = b""
            try:
                if self._process.stdout:
                    stdout_data = await self._process.stdout.read()
                if self._process.stderr:
                    stderr_data = await self._process.stderr.read()
            except Exception:
                pass
            stdout_text = stdout_data.decode(errors="replace").strip()
            stderr_text = stderr_data.decode(errors="replace").strip()
            _LOGGER.warning(
                "frpc 意外退出 (exit code: %d)\n  stdout: %s\n  stderr: %s",
                exit_code,
                stdout_text or "(空)",
                stderr_text or "(空)",
            )

            if self._restart_count >= FRPC_MAX_RESTARTS:
                _LOGGER.error(
                    "frpc 已连续重启 %d 次失败，停止重试。请检查配置和网络。",
                    FRPC_MAX_RESTARTS,
                )
                self._running = False
                return

            self._restart_count += 1
            _LOGGER.info(
                "尝试重启 frpc (%d/%d)，%d 秒后启动...",
                self._restart_count,
                FRPC_MAX_RESTARTS,
                FRPC_RESTART_DELAY,
            )
            await asyncio.sleep(FRPC_RESTART_DELAY)

            success = await self.start(self._binary)
            if success:
                self._restart_count = 0
            else:
                _LOGGER.error("frpc 重启失败 (%d/%d)", self._restart_count, FRPC_MAX_RESTARTS)

    async def ensure_running(self) -> bool:
        if self.is_running:
            return True
        _LOGGER.info("frpc 未运行，尝试启动...")
        return await self.start(self._binary)
