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
