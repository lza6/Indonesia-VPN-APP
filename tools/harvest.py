"""收割 INDONESIA VPN (mobilejumps site40) 全量 OpenVPN 配置（带限流自适应 + 断点续传）。

端点（Laravel, 无鉴权, 但有 429 限流）:
  GET https://site40.mobilejumps.org/public/api/allservers
  GET https://site40.mobilejumps.org/public/api/detail/{slug}

用法: python tools/harvest.py [start_rate_req_per_sec]
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

WORK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECON = os.path.join(WORK, "recon")
OUT = os.path.join(WORK, "output")
CFG_DIR = os.path.join(OUT, "ovpn")
BASE = "https://site40.mobilejumps.org/public/api/"
H = {"User-Agent": "Dart/3.5 (dart:io)", "Accept": "*/*"}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Pacer:
    """全局节流器：按 interval 串行放行，遇 429 自动降速。"""

    def __init__(self, rate):
        self.lock = threading.Lock()
        self.interval = 1.0 / rate
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            at = max(now, self.next_at)
            self.next_at = at + self.interval
        if at > now:
            time.sleep(at - now)

    def slow_down(self, factor=2.0, max_interval=8.0):
        with self.lock:
            self.interval = min(self.interval * factor, max_interval)

    def speed_up(self, factor=1.05, min_interval=0.5):
        with self.lock:
            self.interval = max(self.interval / factor, min_interval)


PACER = Pacer(float(sys.argv[1]) if len(sys.argv) > 1 else 1.0)


def get(path, timeout=30, tries=6):
    delay = 5.0
    for i in range(tries):
        PACER.wait()
        try:
            req = urllib.request.Request(BASE + path, headers=H)
            with OPENER.open(req, timeout=timeout) as r:
                PACER.speed_up()
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                PACER.slow_down()
                print(f"  429 -> backoff {delay:.0f}s (interval={PACER.interval:.2f})", flush=True)
                time.sleep(delay)
                delay = min(delay * 1.6, 45)
                continue
            if e.code in (500, 502, 503, 504):
                time.sleep(delay)
                delay = min(delay * 1.6, 45)
                continue
            return {"_error": f"HTTP {e.code}"}
        except Exception as e:
            if i == tries - 1:
                return {"_error": f"{type(e).__name__}: {e}"}
            time.sleep(delay)
            delay = min(delay * 1.6, 45)
    return {"_error": "retry_exhausted"}


def safe_name(d):
    n = re.sub(r"[^A-Za-z0-9._-]+", "_", d.get("name") or str(d.get("id")))
    c = re.sub(r"[^A-Za-z0-9]+", "_", d.get("country") or "xx")
    return f"{d['id']}_{c}_{n}"[:120]


def parse(item, data):
    cfg = data.get("config") or ""
    path = ""
    if cfg.strip():
        path = os.path.join(CFG_DIR, safe_name(data) + ".ovpn")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(cfg)
    m = re.search(r"^remote\s+(\S+)\s+(\d+)", cfg, re.M)
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "country": data.get("country"),
        "slug": item["slug"],
        "remote": m.group(1) if m else None,
        "port": int(m.group(2)) if m else None,
        "proto": (re.search(r"^proto\s+(\S+)", cfg, re.M) or [None, None])[1],
        "hastcp": data.get("hastcp"),
        "hasudp": data.get("hasudp"),
        "status": data.get("status"),
        "username": data.get("username"),
        "config_len": len(cfg),
        "file": os.path.relpath(path, WORK) if path else None,
        "updated_at": data.get("updated_at"),
    }


def main():
    os.makedirs(CFG_DIR, exist_ok=True)
    servers = json.load(open(os.path.join(RECON, "allservers.json"), encoding="utf-8"))["data"]
    done_path = os.path.join(OUT, "details.json")
    rows = json.load(open(done_path, encoding="utf-8")) if os.path.exists(done_path) else []
    have = {r["slug"] for r in rows if r.get("config_len")}
    todo = [s for s in servers if s["slug"] not in have]
    print(f"total={len(servers)} have={len(have)} todo={len(todo)}", flush=True)
    t0 = time.time()
    for i, item in enumerate(todo, 1):
        d = get("detail/" + item["slug"])
        if "_error" in d:
            rows.append({"id": item["id"], "name": item["name"], "country": item["country"],
                         "slug": item["slug"], "error": d["_error"]})
        else:
            rows.append(parse(item, d.get("data") or {}))
        if i % 25 == 0 or i == len(todo):
            json.dump(rows, open(done_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            ok = sum(1 for r in rows if r.get("config_len"))
            print(f"  {i}/{len(todo)} ok={ok} {time.time()-t0:.0f}s interval={PACER.interval:.2f}", flush=True)
    json.dump(rows, open(done_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    ok = sum(1 for r in rows if r.get("config_len"))
    print(f"done ok={ok} err={len(rows)-ok}")


if __name__ == "__main__":
    main()
