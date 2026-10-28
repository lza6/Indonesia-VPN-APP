# PROTOCOL — 给二次开发/对接方的实现手册

> 目标读者：要在 30 行内把「节点目录 + OpenVPN 配置」拉下来的人。
> 全部内容均为实测（2026-10-29），不是推测。

---

## 1. 常量表

| 名称 | 值 |
|---|---|
| Base URL | `https://site40.mobilejumps.org/public/api/` |
| 目录端点 | `GET allservers` |
| 单节点端点 | `GET detail/{slug}` |
| 必备请求头 | `User-Agent: Dart/3.5 (dart:io)`（浏览器 UA 会被 Cloudflare 403） |
| 目录条数 | 1104（会变，别写死） |
| 限流 | 单 IP ≈ **2 req/s**，超了返回 **429** |
| 响应格式 | JSON，`{"success":true,"message":"...","data":...}` |
| 认证 | **无**（无 token / 无签名 / 无 cookie 要求） |

---

## 2. 发现来源（为什么会是这个地址）

- `libapp.so` 字符串表里唯一的业务 URL 就是上面那个 Base URL（Dart 侧变量名 `_baseUrl`）。
- `GET https://site40.mobilejumps.org/api/` → **301 → `/public/api`**，正文恒为 `endpoint`
  （Laravel 根路由占位路由，`Route::any('/', fn() => 'endpoint')`）。
- 站点技术栈（从响应头读出来的）：`x-powered-by: PHP/7.4.33`、`x-turbo-charged-by: LiteSpeed`、
  `platform: hostinger`、`Server: cloudflare`；Cookie 名 `vpnforindonesia_session`（Laravel APP_NAME）。
- 因此**真实基址是 `/public/api/`**，直接请求 `/api/xxx` 会 404（除了 `/api/` 自身会 301）。

---

## 3. 端点参数表

### 3.1 目录

```http
GET /public/api/allservers   HTTP/1.1
Host: site40.mobilejumps.org
User-Agent: Dart/3.5 (dart:io)
```

无任何查询参数。响应 `data` 是节点数组（字段见 §4）。

### 3.2 单节点配置

```http
GET /public/api/detail/{slug}   HTTP/1.1
Host: site40.mobilejumps.org
User-Agent: Dart/3.5 (dart:io)
```

`{slug}` 来自 `allservers` 的 `slug` 字段（64 字符 base62 随机串）。
响应 `data` = 目录字段 **+ 4 个新字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `username` | `null` | 本机型纯证书认证，无账号 |
| `password` | `null` | 同上 |
| `config` | `string` | **完整 `.ovpn` 文本**（约 4.5 KB，`ca`/`cert`/`key`/`tls-crypt` 全部内联） |
| `hastcp` / `hasudp` | `bool` | 仅声明，当前下发的 `config` 全是 UDP |

---

## 4. 节点对象字段表

| 字段 | 示例 | 备注 |
|---|---|---|
| `id` | `1024` | 稳定自增 |
| `name` | `Montreal - 689` | 展示名 |
| `flag` | `https://mobilejumptech.com/flag/ca.png` | 国旗 CDN（关联域名） |
| `country` | `Canada` / `Indonesia,Jakarta4` | 格式不统一，做分组要先归一化 |
| `slug` | `LbusKsoum...pyQArBLZwi` | 64 字符，取配置的唯一键 |
| `priority` | `4` | 排序权重 |
| `status` | `0` | 未见 1，语义未确证（**待验证**） |
| `created_at` / `updated_at` | `2021-05-09T12:44:44.000000Z` | Laravel 标准时间戳 |
| `hastcp` / `hasudp` | `true` | 声明能力 |

---

## 5. 最小实现骨架（可直接抄）

```python
import json, re, time, urllib.request

BASE = "https://site40.mobilejumps.org/public/api/"
HDR = {"User-Agent": "Dart/3.5 (dart:io)", "Accept": "*/*"}
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绝不走环境代理


def api(path, tries=5):
    """带 429 退避的 GET。单 IP 稳态 ≈2 req/s，别并发打。"""
    delay = 5.0
    for _ in range(tries):
        try:
            req = urllib.request.Request(BASE + path, headers=HDR)
            with op.open(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 45)
    raise RuntimeError("rate limited")


servers = api("allservers")["data"]                 # 1104 条
for s in servers[:3]:
    d = api("detail/" + s["slug"])["data"]
    ovpn = d["config"]                              # 这就是能直接喂给 openvpn 的配置
    remote = re.search(r"^remote\s+(\S+)\s+(\d+)", ovpn, re.M).groups()
    print(s["id"], s["country"], remote)
    time.sleep(0.6)                                 # 礼貌间隔
```

---

## 6. 配置特征（决定它能不能当长期池）

```
proto udp
remote <ip> 1194
cipher AES-128-GCM
auth SHA256
tls-version-min 1.2
<ca> … </ca>          # 每 server IP 一套
<cert> … </cert>      # 客户端证书，Not After 2033–2036
<key> … </key>        # EC prime256v1 私钥，10 年有效
<tls-crypt> … </tls-crypt>   # 静态密钥
```

- **无 `auth-user-pass`** → 不依赖账号，不会因账号封禁而失效。
- 同一 server IP 的多个配置**共用同一套 ca/cert/key/tls-crypt**（唯一性按 IP 计：473 套）。
- 因此「配置数」不等于「出口 IP 数」。要评估池子规模请数唯一 `remote`。

---

## 7. 必避坑清单

| # | 坑 | 现象 | 正确做法 |
|---|---|---|---|
| 1 | 浏览器 UA | `403 Attention Required!`（Cloudflare） | 用 `Dart/3.5 (dart:io)` 或 okhttp UA |
| 2 | 直接用 `/api/xxx` | 404 | 真实基址 `/public/api/` |
| 3 | 高并发拉 detail | 429，之后持续被限 | 串行 + 0.5~1s 间隔 + 429 退避 |
| 4 | 用 TCP 测活 | 全是"不通" | OpenVPN 是 UDP，必须跑 TLS 控制信道握手 |
| 5 | `subprocess.run(timeout=)` 判活 | 存活节点全被记成超时 | 边读 stdout 边判定 `Initialization Sequence Completed` |
| 6 | 拿别家 MobileJump 协议套 | `be-data/v7/server_list` 全 404 | 本站只有 `allservers` + `detail/{slug}` |
| 7 | 同宿主多 tun | tun IP 漂移、10.8.0.0/24 网段冲突 | 每节点一个 netns |
| 8 | netns 里直接用系统 DNS | microsocks 解析域名全失败 | `unshare -m` + `mount --bind` 走隧道的 resolv.conf |
| 9 | fail-closed 只删默认路由 | openvpn 自己 `Network is unreachable` 全灭 | 先 `ip route replace <server>/32 via <veth_gw>` 再删默认路由 |
| 10 | 拿域名验出口 IP | netns DNS 没修好时误判"隧道不通" | 用 IP 直连 `http://208.95.112.1/json/` |

---

## 8. 变更应对

上游若换证/换 IP/改路由，重跑一次 `tools/harvest.py` 即可全量刷新（约 10–16 分钟，受 429 限流决定）。
判断是否需要重跑的信号：`detail/{slug}` 返回的 `config` 里 `remote` 变了，或握手全部 `AUTH_FAILED`。
