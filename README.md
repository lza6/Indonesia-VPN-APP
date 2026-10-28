# INDONESIA VPN (mobilejumps site40) — 节点池逆向与收割

> **仓库关系**：`lza6/Indonesia-VPN-APP`（本仓库，规范命名）与
> `lza6/IndonesiaVPN-APP-2api`（早期命名）为同一份成果，两者同步维护；
> 与 `lza6/Russia-VPN-APP` 同属 mobilejumps 白标平台的两个 `siteNN` 实例（slug 重叠 413/1104）。
>

> APK：`INDONESIA VPN v1.8.5.7 b1857 (Premium by @ElaMods)`
> 包名：`free.vpn.secure.turbo.proxy.hotspot.vpnindonesia`
> 交付日期：2026-10-29

---

## 状态表

| 环节 | 状态 | 证据 |
|---|---|---|
| 架构识别 | ✅ 已验证 | Flutter AOT（Dart 3.12.2）+ ics-openvpn / OpenVPN 3 内核，仅 arm64 |
| 节点目录端点 | ✅ 已验证 | `GET /public/api/allservers` → 1104 条，无鉴权 |
| 单节点配置端点 | ✅ 已验证 | `GET /public/api/detail/{slug}` → 完整 `.ovpn`（ca/cert/key/tls-crypt 内联） |
| 全量收割 | ✅ 已验证 | 1104/1104 配置落盘，0 失败（`output/ovpn/`） |
| 真实握手测活 | ✅ 已验证 | OpenVPN TLS 控制信道握手，判据 `Initialization Sequence Completed` |
| 隧道 → SOCKS5 | ✅ 已验证 | netns 隔离 + fail-closed，`socks5://127.0.0.1:44000+i` |
| 出口 IP 校验 | ✅ 已验证 | 每个端口出口 == 该节点 `remote` IP（直出不中转） |
| 延迟/带宽压测 | ✅ 已验证 | `tools/bench.py`（延迟 / 吞吐 / 并发） |
| demo 页 | ✅ 已验证 | `python demo_server.py` → <http://127.0.0.1:8931> |
| new-api 对接 | 📄 文档就绪 | `docs/NEWAPI_INTEGRATION.md`（走 `TRYINGOPEN_PROXY_FILE`） |

---

## 协议三句话

1. 目录：`GET https://site40.mobilejumps.org/public/api/allservers`（UA 必须非浏览器，否则 Cloudflare 403）
2. 配置：`GET https://site40.mobilejumps.org/public/api/detail/{slug}` → `data.config` 就是完整 `.ovpn`
3. 认证：**纯客户端证书**（`username/password` 为 null），配置内联 EC 私钥 + `tls-crypt` 静态密钥；证书有效期 2033–2036

---

## 快速开始

```powershell
# 0) 依赖：python3 + WSL2(Ubuntu, openvpn + microsocks)
wsl -d Ubuntu -u root -- bash -lc "apt-get install -y openvpn microsocks"

# 1) 拉目录 + 全量配置（内置限流自适应，约 10 分钟）
python tools\harvest.py 1.0

# 2) 真实握手测活（WSL 内跑，8 并发）
wsl -d Ubuntu -u root -- bash -lc "python3 tools/probe_in_wsl.py /mnt/c/vg/ovpn /mnt/c/vg/probe_all.json 8 20"

# 3) 起隧道池（netns 隔离 + fail-closed），输出 socks5://127.0.0.1:44000+i
wsl -d Ubuntu -u root -- bash -lc "python3 tools/pool_wsl.py --alive-json /mnt/c/vg/probe_all.json --ovpn-dir /mnt/c/vg/ovpn --limit 40"

# 4) 压测
python tools\bench.py --rounds 3 --bytes 2000000

# 5) demo 页
python demo_server.py      # http://127.0.0.1:8931
```

---

## 工具清单

| 文件 | 作用 |
|---|---|
| `tools/harvest.py` | 拉 allservers + detail 全量落盘；429 自适应降速 + 断点续传 |
| `tools/probe_in_wsl.py` | 批量真实 OpenVPN 握手测活（流式判定，输出握手耗时） |
| `tools/probe_one.py` | 单节点握手测活（demo 页「测活」按钮后端） |
| `tools/pool_wsl.py` | 每节点一个 netns 的隧道池 → SOCKS5 端口，含 supervisor |
| `tools/bench.py` | SOCKS5 端口的延迟 / 吞吐 / 并发压测 |
| `tools/analyze.py` | 1104 份配置的凭证生命周期与结构分析 |
| `demo_server.py` + `demo.html` | 节点池控制台（零依赖标准库） |
| `docs/REVERSE_REPORT.md` | 完整逆向报告（含全部踩坑） |
| `docs/NEWAPI_INTEGRATION.md` | new-api 代理池对接指南 |

---

## 关键数据

```
配置总数        1104        （89 个国家 / 473 个唯一 server IP）
握手存活        664 配置  →  342 个唯一出口 IP
握手中位        P50 2.41s   P95 6.96s   （UDP 1194 真实 TLS 控制信道握手）
协议            UDP 1194 / AES-128-GCM / tls-crypt / TLS1.2+
认证            客户端证书（EC P-256），无账号密码
证书有效期      2033 ~ 2036（10 年期，签发 2024–2026）
服务器归属      m247 307 · contabo 115 · gcore 84 · cloudfanatic 52 · justhost 33 · melbicom 33 …
```

### 首轮本地压测（30 条隧道常驻池）

| 指标 | 结果 |
|---|---|
| 隧道上线率 | **30 / 30** |
| 出口 IP 校验 | 30/30 均等于节点 `remote`（直出不中转） |
| 延迟 | **P50 215.9 ms · P95 544.2 ms** |
| 吞吐（2 MB 下行） | **P50 14.7 Mbps · 最高 19.24 Mbps** |
| 并发 | 8 并发 8 成功，0.2s 完成 |
| 稳定性 | supervisor 连续 10 min 无掉线 |

按国家取样（存活配置 / 唯一出口 IP）：United States 19 · France 14 · Japan 10 · India 10 ·
Canada 9 · Kazakhstan 8 · Netherland 8 · Singapore 8 · Indonesia 7×6 组。

---

## 合规声明

- 节点为上游运营方自有 / 租用的商业 VPS（Contabo、m247、Gcore 等），**不是** VPNGate 那类公共志愿节点。
- 逆向披露协议与凭证属于研究行为；**「能拿到」不等于「有权用」**。接入对外计费服务属盗用第三方基础设施，风险自负。
- 本项目未利用任何漏洞：两个端点都是公开、无鉴权、无签名的普通 HTTP 路由。
- 建议仅用于自有业务的出口 IP 轮换与自测；上游若换证换 IP，重新跑一次 `harvest.py` 即可。
