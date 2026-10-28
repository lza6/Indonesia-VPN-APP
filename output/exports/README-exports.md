# 导出清单说明

| 文件 | 内容 | 用途 |
|---|---|---|
| `proxies-indonesia.txt` | 30 条 `socks5://127.0.0.1:440xx` | 直接喂 `TRYINGOPEN_PROXY_FILE` |
| `pool-nodes.csv` | 端口 ↔ 节点 ↔ 出口 IP ↔ ISP | 核对出口是否生效 |
| `alive-nodes.csv` | 664 条存活节点 | 想换节点时从这里挑 |
| `alive-unique-ips.txt` | 342 个唯一出口 IP | 估算真实 IP 池规模 |

## 关键提醒

- **端口只在隧道池进程活着时有效**：`tools/pool_wsl.py` 一停，440xx 全部失效。
- 校验出口：「某端口的出口 IP」必须等于「对应节点的 remote IP」；如果等于宿主公网 IP，说明隧道没生效，
  立刻停用该端口（本仓库已做 fail-closed，正常不会发生）。
- 配置数 ≠ IP 数：664 个存活配置只对应 342 个唯一出口 IP（同一 server IP 常挂多份配置）。
