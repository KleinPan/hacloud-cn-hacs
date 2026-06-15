# HA Cloud CN

![hacs validate](https://github.com/KleinPan/hacloud-cn-hacs/actions/workflows/validate.yml/badge.svg)

国内 Home Assistant 云服务的 HA 集成包，作为「HA Cloud CN 服务端 ([HA_Cloud_CN](https://github.com/KleinPan/HA_Cloud_CN))」的客户端。功能对标 Nabu Casa 的官方集成。

## 功能

- **极简配置流程**：只需输入后端地址 + 8 位接入码，自动完成绑定
- **frpc 自动管理**：绑定成功后自动生成 frpc 配置并启动隧道进程，无需手动配置
- **进程守护**：内置 watchdog，frpc 崩溃自动重启（最多 5 次）
- **5 个 sensor 实体**：
  - `sensor.hacloud_zaixianzhuangtai` — 在线状态（"在线" / "离线"）
  - `sensor.hacloud_benyueliuliang` — 本月已用流量（单位 MB）
  - `sensor.hacloud_dingyuedaoqi` — 订阅到期日（YYYY-MM-DD）
  - `sensor.hacloud_yumingxinxi` — 域名信息（含子域名、frps 地址、端口）
  - `sensor.hacloud_suidaozhuangtai` — 隧道状态（"运行中" / "已停止" / "已退出"）
- **通知推送转发**：将 HA 自动化告警转发到企业微信/Telegram/钉钉/邮件/Webhook
- 60 秒周期心跳上报，保持服务端 `endpoint.online=1`

## 安装

### HACS 自定义仓库（推荐）

1. HACS → 集成 → 右上角 ⋮ → **自定义存储库**
2. URL 填本仓库地址，类别选 **Integration**
3. 在 HACS 列表里找到 **HA Cloud CN** → 下载 → 重启 Home Assistant
4. 设置 → 设备与服务 → **添加集成** → 搜 **HA Cloud CN**
5. 填后端地址 + 接入码

### 手动安装

把 `custom_components/hacloud_cn/` 拷贝到你的 HA 配置目录下的 `custom_components/`：

```
<HA-config-dir>/
└─ custom_components/
   └─ hacloud_cn/
      ├─ __init__.py
      ├─ api.py
      ├─ config_flow.py
      ├─ const.py
      ├─ frpc_manager.py
      ├─ manifest.json
      ├─ notify.py
      ├─ sensor.py
      ├─ strings.json
      ├─ brands/
      │  ├─ icon.png
      │  └─ logo.png
      └─ translations/
         ├─ en.json
         └─ zh-Hans.json
```

重启 HA → 添加集成。

## frpc 安装

v0.2 会自动管理 frpc 进程，但需要先安装 frpc 二进制文件。两种方式：

### 方式一：系统 PATH 安装（推荐）

```bash
# 下载 frp（以 arm64 为例，树莓派 / HA Green / HA Yellow）
wget https://github.com/fatedier/frp/releases/download/v0.61.1/frp_0.61.1_linux_arm64.tar.gz
tar xzf frp_0.61.1_linux_arm64.tar.gz
sudo cp frp_0.61.1_linux_arm64/frpc /usr/local/bin/
sudo chmod +x /usr/local/bin/frpc

# 验证
frpc --version
```

### 方式二：HA 配置目录安装

```bash
# 在 HA 配置目录下创建 hacloud_cn 文件夹
mkdir -p /config/hacloud_cn
# 将 frpc 二进制复制进去
cp frpc /config/hacloud_cn/
chmod +x /config/hacloud_cn/frpc
```

> **注意**：集成配置流程的第二步会自动检测 frpc 是否可用，并给出提示。

## 如何拿到「接入码」

1. 浏览器打开 HA Cloud CN 后台
2. 用账号登录
3. 进入 **HA 云端 → 终端管理**
4. 点击 **新增终端**，输入名称（如 "我家HA"），保存
5. 弹窗里复制 8 位接入码（24 小时有效）

## 配置流程

```
第一步：输入后端地址 + 接入码
  ↓
自动绑定 → 获取 token / frpsAddr / frpPort / subdomain
  ↓
第二步：确认 frpc 状态
  - ✅ 检测到 frpc → 自动生成配置并启动隧道
  - ⚠️ 未检测到 → 提示安装，可先跳过
  ↓
完成！隧道自动建立，Home Assistant 可通过子域名远程访问
```

## 排错

- **绑定失败 "接入码无效或已过期"**：检查接入码是否过期；在 HA Cloud 后台「重新生成接入码」
- **隧道状态"已停止"**：检查 frpc 是否安装正确（`which frpc`）；查看 HA 日志中 frpc 相关错误
- **frpc 启动失败**：检查 frpc 版本是否 ≥ 0.52.0（支持 toml 配置格式）；查看 `/config/hacloud_cn/frpc.toml` 配置是否正确
- **后端不可达**：检查后端是否启动；如果 HA 和后端不在同一网络，要用公网域名
- **frpc 连接 frps 失败**：检查服务器 7000 端口是否开放；检查 frps 是否运行
- 详细日志：`Settings → System → Logs`，搜索 `hacloud_cn`

## 协议

MIT。
