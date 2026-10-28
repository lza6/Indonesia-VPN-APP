r"""对隧道池的 SOCKS5 端口做延迟 + 带宽压测（Windows 宿主侧，用 curl 保证不碰环境代理）。

用法:
  python tools/bench.py [--state C:\vg\pool_state.json] [--rounds 3] [--bytes 2000000]
                        [--concurrency 8] [--out output/bench.json]
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

CURL = "curl"
LAT_URL = "http://208.95.112.1/json/?fields=query,country"
SPD_URL = "http://speed.cloudflare.com/__down?bytes={n}"
W = "%{http_code} %{time_connect} %{time_starttransfer} %{time_total} %{speed_download}"


def curl(url, proxy, timeout=30, out_devnull=True):
    args = [CURL, "-s", "--ssl-no-revoke", "-m", str(timeout), "--socks5", proxy,
            "-o", os.devnull if out_devnull else "-", "-w", W, url]
    p = subprocess.run(args, capture_output=True, text=True)
    line = (p.stdout or "").strip().splitlines()
    if not line:
        return None
    parts = line[-1].split()
    if len(parts) < 5:
        return None
    try:
        return {"code": int(parts[0]), "connect": float(parts[1]),
                "ttfb": float(parts[2]), "total": float(parts[3]),
                "speed_bps": float(parts[4])}
    except ValueError:
        return None


def bench_node(t, rounds, nbytes):
    proxy = f"127.0.0.1:{t['public_port']}"
    lat, exit_ip = [], None
    for _ in range(rounds):
        r = curl(LAT_URL + f"&_={int(time.time()*1000)}", proxy, 20)
        if r and r["code"] == 200:
            lat.append(r["ttfb"])
        time.sleep(0.15)
    spd = curl(SPD_URL.format(n=nbytes), proxy, 45)
    return {
        "name": t.get("name"), "country": t.get("country"), "port": t["public_port"],
        "exit_ip": t.get("exit_ip"), "exit_isp": t.get("exit_isp"),
        "lat_ms": [round(x * 1000, 1) for x in lat],
        "lat_med_ms": round(statistics.median(lat) * 1000, 1) if lat else None,
        "speed_mbps": round(spd["speed_bps"] * 8 / 1e6, 2) if spd else None,
        "ok": bool(lat),
    }


def concurrency_test(port, n):
    proxy = f"127.0.0.1:{port}"
    def one(_):
        r = curl(LAT_URL + f"&_={int(time.time()*1000)}", proxy, 25)
        return bool(r and r["code"] == 200)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as ex:
        res = list(ex.map(one, range(n)))
    return {"concurrency": n, "success": sum(res), "secs": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=r"C:\vg\pool_state.json")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--bytes", type=int, default=2000000)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", default="output/bench.json")
    args = ap.parse_args()

    st = json.load(open(args.state, encoding="utf-8"))
    tunnels = st.get("tunnels", [])
    print(f"bench {len(tunnels)} tunnels, rounds={args.rounds}, payload={args.bytes}B", flush=True)
    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(lambda t: bench_node(t, args.rounds, args.bytes), tunnels):
            rows.append(r)
            print(f"  {str(r['country'])[:14]:15s} :{r['port']} exit={str(r['exit_ip']):16s} "
                  f"lat={r['lat_med_ms']}ms spd={r['speed_mbps']}Mbps", flush=True)
    ok = [r for r in rows if r["ok"]]
    lats = sorted(r["lat_med_ms"] for r in ok if r["lat_med_ms"])
    spds = sorted(r["speed_mbps"] for r in ok if r["speed_mbps"])
    conc = None
    if ok:
        best = max(ok, key=lambda r: r["speed_mbps"] or 0)
        conc = concurrency_test(best["port"], args.concurrency)
        conc["port"] = best["port"]
        print(f"concurrency: {conc}", flush=True)
    summary = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "nodes": len(rows), "ok": len(ok), "elapsed_s": round(time.time() - t0, 1),
        "lat_med_ms": lats[len(lats)//2] if lats else None,
        "lat_p95_ms": lats[int(len(lats)*0.95)] if lats else None,
        "speed_med_mbps": spds[len(spds)//2] if spds else None,
        "speed_max_mbps": spds[-1] if spds else None,
        "concurrency": conc,
    }
    json.dump({"summary": summary, "rows": rows}, open(args.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
