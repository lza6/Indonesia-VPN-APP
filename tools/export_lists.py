r"""导出对接用的清单文件（给 new-api / 自建代理池直接用）。

产出（默认 output/exports/）:
  proxies-indonesia.txt   socks5://127.0.0.1:PORT 每行一条（TRYINGOPEN_PROXY_FILE 格式）
  pool-nodes.csv          端口 ↔ 节点 ↔ 出口 IP ↔ ISP ↔ 国家
  alive-nodes.csv         664 条存活节点全表（id/名称/国家/remote/握手耗时）
  alive-unique-ips.txt    342 个唯一出口 IP（裸 IP 列表）
  README-exports.md       清单说明

用法: python tools/export_lists.py [--pool-state C:\vg\pool_state.json]
"""
import argparse
import csv
import json
import os

WORK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(WORK, "output")
EXP = os.path.join(OUT, "exports")
PROBE = os.environ.get("PROBE_ALL", r"C:\vg\probe_all.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool-state", default=r"C:\vg\pool_state.json")
    args = ap.parse_args()
    os.makedirs(EXP, exist_ok=True)

    details = json.load(open(os.path.join(OUT, "details.json"), encoding="utf-8"))
    probe = {r["file"]: r for r in json.load(open(PROBE, encoding="utf-8"))}
    alive = []
    for d in details:
        p = probe.get(os.path.basename(d.get("file") or ""))
        if p and p.get("status") == "ALIVE":
            hs = p.get("handshake_s")
            alive.append({**d, "handshake_s": hs if isinstance(hs, (int, float)) and hs > 0 else None})

    # 1) alive 全表
    with open(os.path.join(EXP, "alive-nodes.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "country", "remote_ip", "port", "proto",
                    "handshake_s", "updated_at", "slug"])
        for d in sorted(alive, key=lambda x: (x["country"] or "", x["id"])):
            w.writerow([d["id"], d["name"], d["country"], d["remote"], d["port"],
                        d["proto"], d["handshake_s"], d.get("updated_at"), d["slug"]])

    # 2) 唯一出口 IP
    ips = sorted({d["remote"] for d in alive if d["remote"]})
    with open(os.path.join(EXP, "alive-unique-ips.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(ips) + "\n")

    # 3) 池端口清单
    pool_rows = []
    if os.path.exists(args.pool_state):
        st = json.load(open(args.pool_state, encoding="utf-8"))
        pool_rows = st.get("tunnels", [])
        lines = ["# INDONESIA VPN tunnel pool — generated %s" % st.get("ts", ""),
                 "# 用法: set TRYINGOPEN_PROXY_FILE=<此文件路径>   (new-api relay/channel/tryingopen)"]
        lines += [t["socks"] for t in pool_rows]
        with open(os.path.join(EXP, "proxies-indonesia.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(EXP, "pool-nodes.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["socks", "public_port", "country", "exit_ip", "exit_isp",
                        "exit_city", "handshake_s", "node_file"])
            for t in pool_rows:
                hs = t.get("handshake_s")
                hs = hs if isinstance(hs, (int, float)) and hs > 0 else None
                w.writerow([t["socks"], t["public_port"], t["country"], t.get("exit_ip"),
                            t.get("exit_isp"), t.get("exit_city"), hs, t.get("file")])

    # 4) 说明
    with open(os.path.join(EXP, "README-exports.md"), "w", encoding="utf-8") as f:
        f.write(f"""# 导出清单说明

| 文件 | 内容 | 用途 |
|---|---|---|
| `proxies-indonesia.txt` | {len(pool_rows)} 条 `socks5://127.0.0.1:440xx` | 直接喂 `TRYINGOPEN_PROXY_FILE` |
| `pool-nodes.csv` | 端口 ↔ 节点 ↔ 出口 IP ↔ ISP | 核对出口是否生效 |
| `alive-nodes.csv` | {len(alive)} 条存活节点 | 想换节点时从这里挑 |
| `alive-unique-ips.txt` | {len(ips)} 个唯一出口 IP | 估算真实 IP 池规模 |

## 关键提醒

- **端口只在隧道池进程活着时有效**：`tools/pool_wsl.py` 一停，440xx 全部失效。
- 校验出口：「某端口的出口 IP」必须等于「对应节点的 remote IP」；如果等于宿主公网 IP，说明隧道没生效，
  立刻停用该端口（本仓库已做 fail-closed，正常不会发生）。
- 配置数 ≠ IP 数：{len(alive)} 个存活配置只对应 {len(ips)} 个唯一出口 IP（同一 server IP 常挂多份配置）。
""")
    print(f"alive={len(alive)} unique_ips={len(ips)} pool_ports={len(pool_rows)}")
    for n in sorted(os.listdir(EXP)):
        p = os.path.join(EXP, n)
        print(f"  {n:26s} {os.path.getsize(p):>8,d} B")


if __name__ == "__main__":
    main()
