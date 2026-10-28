# INDONESIA VPN v1.8.5.7 (b1857, ElaMods Premium) 逆向报告

> 日期：2026-10-29 ｜ 目标：还原节点下发协议 → 收割 OpenVPN 凭证 → 评估能否做成长期稳定代理池
> 结论先说：**能**。1104 份完整 `.ovpn`（含客户端私钥 + tls-crypt 静态密钥）已全部拿到，证书有效期到 2033–2036 年，纯证书认证、无用户名密码、无 token 签发环节。

---

## 1. APK 结构

| 项 | 值 |
|---|---|
| 包名 | `free.vpn.secure.turbo.proxy.hotspot.vpnindonesia` |
| 体积 | 25.7 MB（920 entries） |
| 架构 | **Flutter AOT**（`lib/arm64-v8a/libapp.so` 7.67 MB + `libflutter.so` 11.6 MB，**仅 arm64**） |
| Dart 版本 | `3.12.2 (stable) (Tue Jun 9 01:11:39 2026 -0700)` |
| VPN 内核 | Java 侧 `de.blinkt.openvpn`（ics-openvpn）+ OpenVPN 3 C++（`libopenvpn.so` 6.57 MB）+ `assets/pie_openvpn.{arm64-v8a,armeabi-v7a,x86,x86_64}` |
| 加固 | 无壳（ElaMods 只做了付费解锁，无 dpt/pairip 之类） |
| 埋点/广告 | Firebase analytics/crashlytics、Google Mobile Ads、Unity Ads、AppLovin、Pangle、Facebook Ads、Smaato |

**关键判断**：`lib/` 只有 `arm64-v8a` → x86_64 模拟器无法直跑（Flutter AOT 在 ndk_translation 下 SIGILL 的老问题），动态抓包路线成本高，走静态还原。

---

## 2. 节点下发协议（已实测打通）

### 2.1 发现过程

1. `libapp.so` 字符串表里**只有一个**业务 URL：
   `https://site40.mobilejumps.org/api/`
   （同族线索：`amberchen-12b50.appspot.com`（Firebase 项目，无 RTDB）、`mobilejumptech.com`（国旗图标 CDN）、`amberchenapps.wordpress.com`（隐私政策）、`ip-api.com`（出口 IP 检测））
2. `GET https://site40.mobilejumps.org/api/` → **301 → `/public/api`**，body 恒为 `endpoint`（Laravel 根路由占位）
3. `/public/api/index.php` 响应头暴露技术栈：**Laravel + PHP 7.4.33 + LiteSpeed + Hostinger + Cloudflare**，
   Cookie 名 `vpnforindonesia_session`（Laravel APP_NAME = vpnforindonesia）
4. 路径穷举（611 条候选，以「非 404」为判定）命中 **`allservers`**
5. 从 `allservers` 拿到 `slug` 后，对 slug 组合穷举命中 **`detail/{slug}`**

### 2.2 两个端点（**无鉴权、无 token、无签名**）

```http
GET https://site40.mobilejumps.org/public/api/allservers
User-Agent: Dart/3.5 (dart:io)      # 浏览器 UA 会被 Cloudflare WAF 403
```
```json
{"success":true,"message":"All Servers loaded","data":[
  {"id":1024,"name":"Montreal - 689","flag":"https://mobilejumptech.com/flag/ca.png",
   "country":"Canada","slug":"LbusKsoum...pyQArBLZwi","priority":4,"status":0,
   "created_at":"2021-05-09T12:44:44.000000Z","updated_at":"2025-12-06T13:29:32.000000Z",
   "hastcp":true,"hasudp":true}, ...]}
```
→ **1104 条**，89 个国家。

```http
GET https://site40.mobilejumps.org/public/api/detail/{slug}
```
→ 单条记录追加 4 个字段：

| 字段 | 值 | 说明 |
|---|---|---|
| `username` / `password` | `null` / `null` | **纯证书认证，无账号密码** |
| `config` | 4586 B 字符串 | **完整 OpenVPN 客户端配置**（`ca` / `cert` / `key` / `tls-crypt` 全部内联） |

### 2.3 必须踩过的坑

| 坑 | 现象 | 处理 |
|---|---|---|
| Cloudflare WAF | 浏览器 UA / 空 UA → **403** `Attention Required!` | 必须用 `Dart/3.5 (dart:io)` 或 okhttp 类 UA |
| 目录 vs 前端控制器 | `/api/xxx` 直接 404，`/api/` 自身 301 到 `/public/api` | 真实基址是 `/public/api/` |
| **429 限流** | 5 并发抓 detail 几分钟后开始 429 | 单 IP 稳态 ≈ **2 req/s**；需自适应降速 + 退避重试 |
| `api/owl.php` 403 | 带 `x-rasp-block: 1` | RASP 拦截，不是有效端点 |
| `server_list` 全路径 | 404（是老 MobileJump API 的命名，本站不用） | 别拿别家协议套 |

---

## 3. 凭证与配置分析（1104 份全量）

| 指标 | 值 |
|---|---|
| 配置数 | **1104** |
| 唯一远端 IP | **473**（359 个 IP 被多份配置复用，最多一 IP 挂 17 份） |
| 协议 | `proto udp` 100%，端口 `1194` 100% |
| 加密 | `cipher AES-128-GCM` 100%，`auth SHA256`，`tls-version-min 1.2` |
| 控制信道保护 | `<tls-crypt>` 100% |
| 客户端私钥 | `<key>` 内联 100%（EC prime256v1，客户端证书认证） |
| 需要账号密码 | **0 份**（`auth-user-pass` 不存在） |
| 证书 Subject | `CN=<VPS商>_<地区><序号>`，如 `contabo_australia5`、`m247_...`、`gcore_...` |
| 证书有效期 | **Not After 2033 / 2034 / 2035 / 2036**（10 年期），签发 2024–2026 |
| CA / 客户端密钥 / tls-crypt 复用 | 每 IP 一套（`unique_ca = unique_client_key = unique_tls_crypt = 473`） |
| 服务器归属（证书 CN 前缀） | m247 307 · new* 119 · contabo 115 · gcore 84 · cloudfanatic 52 · vps* 51 · justhost 33 · melbicom 33 · itldc 18 |

**为什么这算「长期稳定」**：
- 证书 10 年有效期 → **不存在按天/按周过期换发的问题**；
- 无 token / 无设备绑定 / 无配额 → 不存在凭证轮换与限流；
- 端点是公开的 Laravel 路由，无签名、无鉴权 → 目录变更时也能立刻重新拉取；
- 配置本身是静态文件（`updated_at` 集中在 2025-12），IP 长期不变。

**代价（必须知道的）**：全部是**机房 IP**（Contabo / m247 / Gcore / Cloudflare-adjacent 等 hosting），
不是住宅 IP。做「换 IP 出口」很好用，但对风控严格的站点（Cloudflare 盾、Google/OpenAI 登录）会更容易被判定为数据中心。

---

## 4. 测活方法（关键：别用 TCP 连通性判活）

OpenVPN 是 UDP，TCP 探测毫无意义。真实判活必须跑 **TLS 控制信道握手**：

```bash
openvpn --config x.ovpn --dev null --ifconfig-noexec --route-noexec \
        --auth-nocache --verb 3 --nobind --connect-timeout 8 --connect-retry-max 1
# 判据：日志出现 "Initialization Sequence Completed"
```
- `--dev null` + `--ifconfig-noexec` + `--route-noexec`：只握手，不建接口、不改路由，适合批量扫。
- 判定要**流式读日志**：连上后进程不会退出，若用 `subprocess.run(timeout=)` 统一超时，
  会把所有存活节点的耗时都记成超时值（本次第一版就踩了，secs 全是 22.0）。
- 反例：本文件 v1 的 `secs` 列无意义，v2 改成边读边判定后才有真实握手耗时。

---

## 5. 隧道 → SOCKS5（池化方案）

**第一版（失败）**：同宿主起多个 tun + 源地址策略路由 + microsocks 绑 tun IP。
踩到两个坑：
1. 服务端会重新 push ifconfig，**tun IP 会漂移**，绑死旧 IP 的 microsocks 立刻失效；
2. 多个 tun 拿到**同一个 10.8.0.0/24 网段**，同宿主路由互相打架。

**第二版（当前）**：**每节点一个 network namespace**：

```
宿主机 0.0.0.0:44000+i  --TCP relay-->  10.200.{i}.2:34000+i
                                          └─ netns vpn{i}
                                              ├─ veth vg{i} 10.200.{i}.2/30
                                              ├─ openvpn → tun0（自带 redirect-gateway，命名空间内互不干扰）
                                              └─ microsocks（bind 0.0.0.0，仅该 ns 内可见）
```

三个必须做对的细节：

1. **DNS**：netns 里的 `/etc/resolv.conf` 仍指向 WSL 宿主 DNS（`10.255.255.254`），经隧道不可达 →
   microsocks 解析域名全部失败。解法：`unshare -m` 独立 mount namespace + `mount --bind` 一份
   `nameserver 1.0.0.1 / 1.1.1.1`（走隧道）的 resolv.conf 再 exec microsocks。
2. **fail-closed**：隧道建立后**删掉 netns 里经 veth 的默认路由**。
   否则隧道一断，流量回落 veth → 宿主 `MASQUERADE` → **泄漏成宿主真实 IP**
   （实测到过一次：某端口出口返回了本机 183.250.230.8）。
3. **宿主机零改动**：不加路由、不建 TUN、不碰 `10808`，与 v2rayN/xray 完全隔离。

验证（Windows 宿主侧）：

```
$ curl --socks5 127.0.0.1:44000 http://208.95.112.1/json/
{"country":"Canada","query":"167.160.94.156"}   # == 该节点 remote IP，直出不中转
```

---

## 6. 合规红线

- 节点是**上游运营方自有/租用的 VPS**（Contabo、m247、Gcore…），不是公共志愿节点（VPNGate 那类）。
- 「凭证可获取」≠「有使用权」。把别人付费基础设施挂进对外计费代理池属于盗用，风险自负。
- 本仓库只做协议还原与自用研究；不绕过、不利用任何漏洞，全部是公开的无鉴权 HTTP 路由。
- 建议：只用于自有业务的出口 IP 轮换，不做对外售卖；被上游发现可能整体换证（届时需重新拉一次）。

---

## 7. 首轮实测数据（2026-10-29）

### 7.1 全量握手测活（1104 配置，WSL Ubuntu 8 并发）

```
ALIVE       664   (60.1%)
FATAL(无响应) 416   ← 日志 "All connections have been connect-retry-max (1) times unsuccessful"
TLS_ERROR    20
TIMEOUT       4
handshake: P50 2.41s  P95 6.96s  max 19.66s
```

> 对 440 个非 ALIVE 节点用 **connect-timeout 30s / 总超时 35s** 复测，只捞回极少（≈2/120），
> 说明失败不是超时太短导致的误杀，是节点真的下线。
> 同时这证明了 `ERROR` 与 `TIMEOUT` 在语义上等价（都是 server_poll timeout），
> 分类时不必分开统计。

**配置数 ≠ 出口 IP 数**：664 个存活配置只对应 **342 个唯一出口 IP**
（同一个 IP 往往挂 2–17 份配置，/32 出口相同）。评估池子规模要按唯一 IP 数算。

### 7.2 隧道池压测（30 条常驻，印尼/新加坡/日本/美国优先）

| 指标 | 值 |
|---|---|
| 上线率 | 30/30 |
| 出口 IP 一致性 | 30/30 == 节点 remote IP |
| 延迟 | P50 **215.9 ms**，P95 544.2 ms |
| 吞吐（2 MB） | P50 **14.7 Mbps**，max 19.24 Mbps |
| 并发 | 8/8 成功，0.2s |
| 典型 ISP | Cloudfanatic、PT Media Antar Nusa、Industri Kreatif Digital、CV. NATANETWORK、Internet Inti Saja、PT EXABYTES |

### 7.3 第二次踩坑：fail-closed 会打死 openvpn 自己

第一版 fail-closed 只是删掉 netns 的默认路由，结果 30 条隧道在 90 秒内**全部**
`write UDPv4 []: Network is unreachable → Exiting due to fatal error`。
原因：删默认路由的同时也把 openvpn 到 VPN 服务器的路径删掉了
（`redirect-gateway` 生成的 /32 主机路由并不总存在）。

正确顺序：
```bash
ip route replace <server_ip>/32 via <veth_gw>   # 先补服务器主机路由
ip route del default via <veth_gw>              # 再删默认路由 → fail-closed
```
改完后 30/30 稳定常驻，兜底路径没了，隧道断也不会泄漏成宿主 IP。

### 7.4 其它运维教训

- `setsid nohup ... &` 常驻，否则 WSL 会话结束时子进程被回收；
- `pkill -f pool_wsl.py` 会**匹配到自己那条 bash 命令行**（因为命令行里就含这个字符串），
  要用 `pkill -f 'python3 tools/pool_w[s]l.py'` 这种括号写法；
- 判活一定要流式读日志：`subprocess.run(timeout=)` 会把存活节点全记成超时；
- 出口 IP 校验要用 **IP 直连**（`http://208.95.112.1/json/`）而不是域名：
  netns 内 DNS 未修好时域名解析会失败，看起来像"隧道不通"。
