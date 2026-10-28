"""把已测活的 OpenVPN 配置变成可用的 SOCKS5 代理端口（WSL 内 root 运行）。

架构（每节点一个 network namespace，彻底隔离 + fail-closed）:
  宿主机 --veth--> netns(vpnN) 内: openvpn(tun0, redirect-gateway, 删默认路由) + microsocks
  宿主机 0.0.0.0:44000+i --TCP 转发--> 10.200.{i}.2:34000+i

关键安全设计:
  - fail-closed: 隧道建立后删除 netns 里经 veth 的默认路由。隧道一断，流量无处回落，
    不会泄漏成宿主真实 IP（v1 策略路由版踩过这个坑）。
  - DNS: 用独立 mount namespace 绑定挂载走隧道的 resolv.conf，避免 netns 内解析走宿主。
  - supervisor: 每 30s 复查 openvpn 进程 + 路由 + 出口 IP，死了就把 relay 摘掉并更新 state。

用法:
  python3 pool_wsl.py --alive-json probe.json --ovpn-dir /mnt/c/vg/ovpn --limit 20
"""
import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import threading
import time

SOCKS_BASE = 34000
PUBLIC_BASE = 44000
SUBNET = "10.200.{}.{}"
RESOLV = "/mnt/c/vg/resolv_vpn.conf"
IPAPI_IP = "208.95.112.1"
HEALTH_EVERY = 120


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


class Tunnel:
    def __init__(self, idx, node, workdir):
        self.idx = idx
        self.node = node
        self.ns = f"vpn{idx}"
        self.vh = f"vh{idx}"
        self.vg = f"vg{idx}"
        self.host_ip = SUBNET.format(idx, 1)
        self.ns_ip = SUBNET.format(idx, 2)
        self.socks_port = SOCKS_BASE + idx
        self.public_port = PUBLIC_BASE + idx
        self.log = os.path.join(workdir, f"tun{idx}.log")
        self.proc = None
        self.state = "init"
        self.err = ""
        self.exit_ip = None
        self.relay = None
        self.checked_at = 0

    def setup_ns(self):
        sh(f"ip netns del {self.ns} 2>/dev/null")
        sh(f"ip link del {self.vh} 2>/dev/null")
        sh(f"ip netns add {self.ns} && "
           f"ip link add {self.vh} type veth peer name {self.vg} && "
           f"ip link set {self.vg} netns {self.ns} && "
           f"ip addr add {self.host_ip}/30 dev {self.vh} && "
           f"ip link set {self.vh} up && "
           f"ip netns exec {self.ns} ip addr add {self.ns_ip}/30 dev {self.vg} && "
           f"ip netns exec {self.ns} ip link set {self.vg} up && "
           f"ip netns exec {self.ns} ip link set lo up && "
           f"ip netns exec {self.ns} ip route add default via {self.host_ip} && "
           f"ip netns exec {self.ns} sysctl -qw net.ipv6.conf.all.disable_ipv6=1")
        return True

    def start_vpn(self):
        cmd = (f"ip netns exec {self.ns} openvpn --config '{self.node['path']}' "
               f"--dev tun0 --auth-nocache --verb 3 --nobind "
               f"--connect-timeout 10 --connect-retry-max 5")
        self.proc = subprocess.Popen(cmd, shell=True, stdout=open(self.log, "w"),
                                     stderr=subprocess.STDOUT, text=True)
        t0 = time.time()
        while time.time() - t0 < 25:
            time.sleep(0.5)
            txt = open(self.log, errors="replace").read()
            if "Initialization Sequence Completed" in txt:
                self.state = "connected"
                return True
            if re.search(r"AUTH_FAILED|VERIFY ERROR|TLS Error|Cannot resolve", txt):
                self.err = [l for l in txt.splitlines()
                            if re.search(r"AUTH_FAILED|VERIFY ERROR|TLS Error|Cannot resolve", l)][-1][-120:]
                self.state = "failed"
                return False
            if self.proc.poll() is not None:
                self.err = "process exited"
                self.state = "failed"
                return False
        self.err = "timeout"
        self.state = "failed"
        return False

    def fail_closed(self):
        """删掉经 veth 的默认路由：隧道一断，流量没有回落路径，不会泄漏成宿主 IP。

        注意顺序：必须先给 VPN 服务器补 /32 主机路由，否则删默认路由后
        openvpn 自己都发不出包（日志表现为 write UDPv4: Network is unreachable）。
        """
        remote = self.remote_ip()
        if remote:
            sh(f"ip netns exec {self.ns} ip route replace {remote}/32 via {self.host_ip} 2>/dev/null")
        sh(f"ip netns exec {self.ns} ip route del default via {self.host_ip} 2>/dev/null")
        out = sh(f"ip netns exec {self.ns} ip route get 8.8.8.8 2>/dev/null")
        return "tun0" in out

    def remote_ip(self):
        try:
            txt = open(self.node["path"], encoding="utf-8", errors="replace").read()
            m = re.search(r"^remote\s+(\S+)", txt, re.M)
            return m.group(1) if m else None
        except Exception:
            return None

    def start_socks(self):
        cmd = (f"ip netns exec {self.ns} unshare -m --propagation private sh -c "
               f"'mount --bind {RESOLV} /etc/resolv.conf && exec microsocks -i 0.0.0.0 -p {self.socks_port}'")
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

    def check_exit_ip(self):
        out = sh(f"ip netns exec {self.ns} timeout 12 curl -s -m 10 "
                 f"'http://{IPAPI_IP}/json/?fields=status,country,countryCode,city,isp,query'")
        self.checked_at = time.time()
        try:
            j = json.loads(out)
            if j.get("status") == "success":
                self.exit_ip = j
                return j
        except Exception:
            pass
        return None

    def healthy(self):
        if self.proc is None or self.proc.poll() is not None:
            return False
        r = sh(f"ip netns exec {self.ns} ip route get 8.8.8.8 2>/dev/null")
        return "tun0" in r

    def cleanup(self):
        if self.relay:
            try:
                self.relay.close()
            except Exception:
                pass
        sh(f"ip netns del {self.ns} 2>/dev/null")
        sh(f"ip link del {self.vh} 2>/dev/null")


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def make_relay(loop, t):
    async def handler(r, w):
        try:
            tr, tw = await asyncio.open_connection(t.ns_ip, t.socks_port)
        except Exception:
            w.close()
            return
        await asyncio.gather(pipe(r, tw), pipe(tr, w))
    return asyncio.run_coroutine_threadsafe(
        asyncio.start_server(handler, "0.0.0.0", t.public_port), loop).result()


def write_state(path, tunnels):
    ok = [t for t in tunnels if t.state == "ok"]
    state = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "count": len(ok),
        "total": len(tunnels),
        "tunnels": [{
            "idx": t.idx, "name": t.node["name"], "country": t.node["country"],
            "exit_ip": (t.exit_ip or {}).get("query"),
            "exit_isp": (t.exit_ip or {}).get("isp"),
            "exit_city": (t.exit_ip or {}).get("city"),
            "socks": f"socks5://127.0.0.1:{t.public_port}",
            "public_port": t.public_port,
            "handshake_s": t.node["hs"], "file": t.node["file"],
            "state": t.state,
        } for t in ok],
        "failed": [{"name": t.node["name"], "err": t.err} for t in tunnels if t.state == "failed"][:50],
    }
    json.dump(state, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alive-json", required=True)
    ap.add_argument("--ovpn-dir", required=True)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--state", default="/mnt/c/vg/pool_state.json")
    ap.add_argument("--logdir", default="/mnt/c/vg/logs")
    ap.add_argument("--countries", default="")
    args = ap.parse_args()

    os.makedirs(args.logdir, exist_ok=True)
    with open(RESOLV, "w", encoding="utf-8") as f:
        f.write("nameserver 1.0.0.1\nnameserver 1.1.1.1\noptions timeout:2 attempts:2\n")
    sh("sysctl -qw net.ipv4.ip_forward=1")
    sh("iptables -t nat -C POSTROUTING -s 10.200.0.0/16 -j MASQUERADE 2>/dev/null || "
       "iptables -t nat -A POSTROUTING -s 10.200.0.0/16 -j MASQUERADE")

    data = json.load(open(args.alive_json, encoding="utf-8"))
    nodes = []
    for a in data:
        if a["status"] != "ALIVE":
            continue
        p = os.path.join(args.ovpn_dir, a["file"])
        if not os.path.exists(p):
            continue
        base = os.path.basename(a["file"])[:-5]
        country = base.split("_")[1] if "_" in base else "??"
        nodes.append({"file": a["file"], "path": p, "country": country,
                      "hs": a.get("handshake_s"), "name": base})
    nodes.sort(key=lambda n: (n["hs"] if n["hs"] is not None else 99))
    if args.countries:
        want = set(args.countries.split(","))
        nodes = [n for n in nodes if n["country"] in want] + [n for n in nodes if n["country"] not in want]
    nodes = nodes[:args.limit]
    print(f"starting {len(nodes)} tunnels (netns isolation, fail-closed)", flush=True)

    tunnels = [Tunnel(i, n, args.logdir) for i, n in enumerate(nodes)]

    def bring_up(t):
        t.setup_ns()
        if not t.start_vpn():
            return
        if not t.fail_closed():
            t.err = "fail-closed check failed (no tun route)"
            t.state = "failed"
            return
        t.start_socks()
        if t.check_exit_ip():
            t.state = "ok"
        else:
            t.err = "exit-ip check failed"
            t.state = "failed"

    ths = []
    for t in tunnels:
        th = threading.Thread(target=bring_up, args=(t,), daemon=True)
        th.start()
        ths.append(th)
        time.sleep(0.4)
    for th in ths:
        th.join(timeout=120)

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    for t in tunnels:
        if t.state == "ok":
            t.relay = make_relay(loop, t)
        ip = t.exit_ip or {}
        print(f"[{t.idx:02d}] {t.node['name'][:46]:48s} {t.state:6s} "
              f"exit={ip.get('query','-'):16s} {ip.get('country','')[:14]:15s} "
              f"pub={t.public_port} {t.err[:40]}", flush=True)
    st = write_state(args.state, tunnels)
    print(f"ok={st['count']}/{len(tunnels)}  state -> {args.state}", flush=True)

    stop = {"f": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(f=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(f=True))
    last_health = time.time()
    try:
        while not stop["f"]:
            time.sleep(5)
            changed = False
            for t in tunnels:
                if t.state == "ok" and not t.healthy():
                    t.fail_streak = getattr(t, "fail_streak", 0) + 1
                    if t.fail_streak < 2:
                        continue
                    t.state = "dead"
                    t.err = "tunnel down"
                    if t.relay:
                        loop.call_soon_threadsafe(t.relay.close)
                    print(f"[{t.idx:02d}] DEAD {t.node['name'][:40]}", flush=True)
                    changed = True
            if time.time() - last_health > HEALTH_EVERY:
                last_health = time.time()
                for t in tunnels:
                    if t.state == "ok":
                        if not t.check_exit_ip():
                            t.state = "suspect"
                            changed = True
                        else:
                            t.state = "ok"
                if changed:
                    write_state(args.state, tunnels)
            if changed:
                st = write_state(args.state, tunnels)
                print(f"re-state ok={st['count']}", flush=True)
            if all(t.state in ("dead", "failed") for t in tunnels):
                if time.time() - getattr(main, "_t0", 0) < 60:
                    time.sleep(5)
                    continue
                print("all tunnels lost, exiting", flush=True)
                break
    finally:
        for t in tunnels:
            t.cleanup()
        print("cleanup done", flush=True)


if __name__ == "__main__":
    main()
