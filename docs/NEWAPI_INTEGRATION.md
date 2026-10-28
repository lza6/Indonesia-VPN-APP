# 对接 new-api 代理池指南

面向「new-api 对接会话」：把本项目的 SOCKS5 端口喂给 `relay/channel/tryingopen` 的代理池。

---

## 1. 一句话链路

```
[app 上游] --HTTP--> site40.mobilejumps.org  (allservers / detail)
                         │
                         ├─ tools/harvest.py        → output/ovpn/*.ovpn (1104)
                         ├─ tools/probe_in_wsl.py   → alive 列表（真实 OpenVPN 握手）
                         └─ tools/pool_wsl.py       → netns 隧道 → socks5://127.0.0.1:44000+i
                                                        │
                                            TRYINGOPEN_PROXY_FILE
                                                        │
                                                   new-api（代理池）
```

---

## 2. 代理池文件格式（已核对源码）

`new-api/relay/channel/tryingopen/proxy_pool.go` 的 `LoadProxies()`：
**每行一个代理 URL，`#` 开头为注释**，支持 `http://user:pass@host:port` 与 `socks5://host:port`。

因此 demo 的 `/api/export/socks` 输出可直接落盘：

```bash
curl -s http://127.0.0.1:8931/api/export/socks > C:\vg\proxies-indonesia.txt
```

内容形如：

```
# INDONESIA VPN tunnel pool, 2026-10-29
socks5://127.0.0.1:44000
socks5://127.0.0.1:44001
...
```

然后设环境变量（Windows 服务方式启动 new-api 时用系统环境变量）：

```
TRYINGOPEN_PROXY_FILE=C:\vg\proxies-indonesia.txt
```

> 注意：源码里 `TRYINGOPEN_FREE_CACHE_FILE` 优先于 `TRYINGOPEN_PROXY_FILE` 加载，
> 同目录下若存在 free cache 文件会先读它，联调时记得清掉或重定向。

---

## 3. 端口规划（不与现有服务冲突）

| 用途 | 端口段 |
|---|---|
| SOCKS5 对外端口（宿主机可直连，WSL localhostForwarding） | `44000 + i` |
| netns 内 microsocks（仅命名空间内） | `34000 + i` |
| netns veth 网段 | `10.200.{i}.1` / `10.200.{i}.2` |
| 隧道 tun | 各 netns 内固定 `tun0` |
| demo 页 | `127.0.0.1:8931` |
| **不碰** | `10808/10809`（v2rayN/xray）、`7890` |

启动示例（管理员 PowerShell / WSL root）：

```powershell
wsl.exe -d Ubuntu -u root -- bash -lc "cd /mnt/c/Users/Administrator.DESKTOP-EGNE9ND/Desktop/逆向产物/IndonesiaVPN_1.8.5.7 && python3 tools/pool_wsl.py --alive-json /mnt/c/vg/probe_all.json --ovpn-dir /mnt/c/vg/ovpn --limit 40 --state /mnt/c/vg/pool_state.json"
```

---

## 4. 池子运维建议

| 事项 | 建议 |
|---|---|
| 规模 | 单机 30–50 条隧道稳定；每条 openvpn 常驻约 10 MB RSS |
| 健康 | `pool_wsl.py` 内置 supervisor：进程死亡 / 路由丢失 / 出口 IP 校验失败 → 摘掉 relay 并更新 `pool_state.json` |
| 重连 | 上游 push `ping 10, ping-restart 120`，掉线会自愈；**不要**在隧道里再套 keepalive |
| IP 稳定性 | 同一 server IP 的配置共用一个 `/32` 出口；想换 IP 就换 `remote`（473 个不同 IP 可选） |
| 轮换策略 | 建议「按国家分桶」：`--countries Indonesia,Singapore,US`，同一业务固定用同一桶，避免风控跳变 |
| 反泄漏 | 已做 fail-closed（删 netns 默认路由）。**切勿**改成 `--redirect-gateway` 直接上宿主路由 |
| 上游限流 | `detail/{slug}` 单 IP ≈ 2 req/s，别高并发重拉；配置本身可长期缓存，不必天天拉 |

---

## 5. 自检清单（对接前跑一遍）

```bash
# 1) 池内端口是否都通、出口 IP 是否各不相同
python tools/bench.py --rounds 2 --bytes 500000

# 2) 单端口真实访问
curl --socks5 127.0.0.1:44000 http://208.95.112.1/json/

# 3) new-api 侧看到池子条数
#    启动后看 tryopen 代理池统计（/api/... 或日志里的 pool size）
```

判定标准：
- `bench.py` 的 `ok == nodes`；
- 每个端口的 `exit_ip` **等于**该节点 `.ovpn` 里的 `remote`（若等于宿主公网 IP = 隧道没生效，必须停止接入）；
- 并发 8 全成功。

---

## 6. 已知限制

- 全部机房 IP（Contabo/m247/Gcore…），对 Cloudflare 盾友好的站点通过率低于住宅代理；
- 上游是第三方基础设施，**对方换证/换 IP 后需重新 `harvest.py`**（一条命令，约 10 分钟）；
- 不支持只走 TCP 的站点场景（配置全是 UDP/1194；`hastcp` 字段为 true 但当前下发只有 UDP 配置）。

---

## 7. 四个必避坑（2026-10-29 读 new-api 源码确认，Russia VPN 对接时补充）

以下四点是同平台 Russia VPN（`lza6/Russia-VPN-APP`）对接时逐行核对源码确认的，
**对 Indonesia 这批节点同样成立**，对接前务必过一遍。

### 7.1 文件加载的代理**不会**被真实出口拨测

```go
// proxy_pool.go TraceProbes()
for _, e := range proxyPool {
    if e.source != "free" {   // ← 住宅/文件源直接跳过
        continue
    }
```
`TRYINGOPEN_PROXY_FILE` 加载出来的条目 `source="residential"`，源码注释写明
"住宅代理跳过（host 即出口，且有凭据不宜外发第三方）"。
**所以 new-api 不会帮你验证出口 IP** —— 正确性必须由转换层（`pool_wsl.py` 的
`check_exit_ip()`）自己保证，这也是本项目每条隧道都要过出口校验的原因。

### 7.2 容器里 `127.0.0.1` 指的是容器自己，不是宿主

转换层跑在宿主/WSL 上时，清单里的 `socks5://127.0.0.1:44000` 在容器内**连不通**。
三选一：

| 方案 | 做法 | 代价 |
|------|------|------|
| A. `extra_hosts` | 清单改 `socks5://host.docker.internal:44000`，并给 new-api 加 `host.docker.internal:host-gateway`；转发器要绑 `0.0.0.0` 而非 `127.0.0.1` | 端口从本机扩到内网可见，需配合防火墙 |
| B. `network_mode: host` | 清单保持 `127.0.0.1` | 失去容器网络隔离 |
| C. 转换层进同一 compose 网络 | 清单写 `socks5://<服务名>:44000` | 需要把 `pool_wsl.py` 容器化（`--privileged` + `/dev/net/tun`） |

### 7.3 可以**追加**而不是替换现有代理源

`TRYINGOPEN_PROXY_FILE` 支持**逗号分隔多文件**（源码注释明写"住宅清单 + 本地协议转换层
天然是两份来源，没必要让运维手动合并"）：

```
TRYINGOPEN_PROXY_FILE=/app/proxies/residential.txt,/app/proxies/indonesia.txt
```

两者都会以 `source="residential"` / `healthScore=1.0` 进池，重复 URL 自动去重。
**不需要动现有的住宅代理配置**，这也是最安全的灰度方式。

### 7.4 冷却与熔断参数（决定"看起来池子很大但很快没可用"）

- **429 冷却**：按 24h 窗口内的使用次数递增 `0 → 30s → 90s → 300s → 900s`
  （`TRYINGOPEN_USE_COOLDOWN_MAP` 可覆盖）。端口数少时会迅速整池冷却。
- **其它失败**：固定 30s 冷却。
- **全局熔断**：同一代理连续失败 **5** 次 → 进入 **10 分钟**全局冷却（`globalFailThreshold`）。
  隧道抖动造成的集中失败会表现为"整池突然没可用"，别误判成节点全死。
- **每日限额**：`TRYINGOPEN_PROXY_MAX_USE_PER_DAY`（0=不限）。端口数固定时建议设上限。

---

## 8. 验证必须三层（只看池快照 ≠ 接通）

```bash
# ① 隧道层：出口 IP 是否 == 该节点标称国家（本项目实测每端口直出不中转）
ip netns exec vpn0 curl -s "http://208.95.112.1/json/?fields=query,country,isp"

# ② 池层：确认 source=residential 里出现你的 indonesia 条目
curl -s "$BASE/api/twoapi/proxy_pool?page_size=50" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.'

# ③ 业务层（唯一能证明"流量真走了它"的一层）
#    发一个真实请求，然后在上游侧/抓包核对来源 IP 与目的端口
curl -s "$BASE/v1/chat/completions" -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"tryingopen/qwen/qwen3.8-flash","messages":[{"role":"user","content":"hi"}]}'
```

**② 有条目不等于流量走了这条代理**，这是同平台上最容易出现的假验证。
