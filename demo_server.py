"""INDONESIA VPN (mobilejumps site40) 节点池 demo 服务。

纯标准库，无第三方依赖。默认 127.0.0.1:8931。

端点:
  GET /                      demo 页面
  GET /api/summary           统计概览
  GET /api/countries         国家分布
  GET /api/nodes             节点表（支持 q/country/state/limit/offset）
  GET /api/pool              当前隧道池（SOCKS5 端口 + 真实出口 IP）
  GET /api/config?id=        单个节点 .ovpn（证书/私钥/静态密钥已脱敏）
  GET /api/export/socks      socks5:// 列表（给 new-api 代理池用）
  GET /api/probe?id=         对单节点做一次真实 OpenVPN 握手测活（走 WSL）

用法: python demo_server.py [port]
"""
import json
import os
import subprocess
import sys
import urllib.parse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WORK = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(WORK, "output")
POOL_STATE = os.environ.get("POOL_STATE", r"C:\vg\pool_state.json")
WSL_OVPN_DIR = os.environ.get("WSL_OVPN_DIR", "/mnt/c/vg/ovpn")
PROBE_ALL = os.environ.get("PROBE_ALL", r"C:\vg\probe_all.json")

_cache = {}


def load_details():
    if "details" not in _cache:
        p = os.path.join(OUT, "details.json")
        _cache["details"] = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []
    return _cache["details"]


def load_probe():
    p = PROBE_ALL
    if not os.path.exists(p):
        p = r"C:\vg\probe_r1.json"
    if not os.path.exists(p):
        return {}
    st = os.stat(p)
    key = ("probe", p, st.st_mtime)
    if key not in _cache:
        rows = json.load(open(p, encoding="utf-8"))
        _cache[key] = {r["file"]: r for r in rows}
        _cache["probe_src"] = p
    return _cache[key]


def load_pool():
    if not os.path.exists(POOL_STATE):
        return {"count": 0, "tunnels": [], "total": 0}
    try:
        return json.load(open(POOL_STATE, encoding="utf-8"))
    except Exception:
        return {"count": 0, "tunnels": [], "total": 0}


def merged_nodes():
    probe = load_probe()
    rows = []
    for d in load_details():
        if not d.get("config_len"):
            continue
        fname = os.path.basename(d["file"])
        pr = probe.get(fname) or {}
        rows.append({
            "id": d["id"], "name": d["name"], "country": d["country"],
            "remote": d["remote"], "port": d["port"], "proto": d["proto"],
            "hastcp": d.get("hastcp"), "hasudp": d.get("hasudp"),
            "updated_at": d.get("updated_at"),
            "slug": d["slug"], "file": d["file"],
            "state": pr.get("status", "untested"),
            "handshake_s": pr.get("handshake_s"),
        })
    return rows


def mask_config(cfg):
    out = []
    section = None
    for line in cfg.splitlines():
        low = line.strip().lower()
        if low in ("<ca>", "<cert>", "<key>", "<tls-crypt>", "<tls-auth>"):
            section = low
            out.append(line)
            out.append("  [已脱敏: 真实 PEM/静态密钥不在此展示]")
            continue
        if low.startswith("</"):
            section = None
            out.append(line)
            continue
        if section and not line.startswith("-----BEGIN") and not line.startswith("-----END"):
            continue
        out.append(line)
    return "\n".join(out)


class Handler(BaseHTTPRequestHandler):
    server_version = "IndonesiaVPN-Demo/1.0"

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        try:
            if path in ("/", "/index.html"):
                html = open(os.path.join(WORK, "demo.html"), encoding="utf-8").read()
                return self._send(200, html, "text/html; charset=utf-8")
            if path == "/api/summary":
                nodes = merged_nodes()
                pool = load_pool()
                by_state = Counter(n["state"] for n in nodes)
                countries = {n["country"] for n in nodes}
                hs = sorted(n["handshake_s"] for n in nodes if n["handshake_s"])
                return self._send(200, {
                    "nodes_total": len(nodes),
                    "countries": len(countries),
                    "alive": by_state.get("ALIVE", 0),
                    "timeout": by_state.get("TIMEOUT", 0),
                    "failed": by_state.get("AUTH_FAILED", 0) + by_state.get("TLS_ERROR", 0) + by_state.get("ERROR", 0),
                    "untested": by_state.get("untested", 0),
                    "handshake_median_s": hs[len(hs) // 2] if hs else None,
                    "handshake_p95_s": hs[int(len(hs) * 0.95)] if hs else None,
                    "pool_up": pool.get("count", 0),
                    "pool_total": pool.get("total") or len(pool.get("tunnels", [])),
                    "probe_src": _cache.get("probe_src"),
                })
            if path == "/api/countries":
                nodes = merged_nodes()
                alive = Counter(n["country"] for n in nodes if n["state"] == "ALIVE")
                total = Counter(n["country"] for n in nodes)
                rows = [{"country": c, "total": total[c], "alive": alive.get(c, 0)}
                        for c in total]
                rows.sort(key=lambda r: (-r["alive"], -r["total"]))
                return self._send(200, rows[:80])
            if path == "/api/nodes":
                nodes = merged_nodes()
                kw = (q.get("q", [""])[0] or "").lower()
                country = q.get("country", [""])[0]
                state = q.get("state", [""])[0]
                limit = min(int(q.get("limit", ["80"])[0]), 500)
                offset = int(q.get("offset", ["0"])[0])
                if kw:
                    nodes = [n for n in nodes
                             if kw in (n["name"] or "").lower() or kw in (n["country"] or "").lower()
                             or kw in str(n["remote"])]
                if country:
                    nodes = [n for n in nodes if n["country"] == country]
                if state:
                    nodes = [n for n in nodes if n["state"] == state]
                return self._send(200, {"total": len(nodes), "rows": nodes[offset:offset + limit]})
            if path == "/api/pool":
                return self._send(200, load_pool())
            if path == "/api/config":
                nid = q.get("id", [""])[0]
                for d in load_details():
                    if str(d.get("id")) == nid and d.get("config_len"):
                        cfg = open(os.path.join(WORK, d["file"]), encoding="utf-8").read()
                        return self._send(200, {"id": nid, "name": d["name"],
                                                "config": mask_config(cfg)})
                return self._send(404, {"error": "not found"})
            if path == "/api/export/socks":
                pool = load_pool()
                lines = [t["socks"] for t in pool.get("tunnels", [])]
                return self._send(200, "\n".join(lines) + "\n", "text/plain; charset=utf-8")
            if path == "/api/probe":
                nid = q.get("id", [""])[0]
                for d in load_details():
                    if str(d.get("id")) == nid:
                        wsl_path = f"{WSL_OVPN_DIR}/{os.path.basename(d['file'])}"
                        script = os.path.join(WORK, "tools", "probe_one.py").replace("\\", "/")
                        wsl_script = "/mnt/c/" + script.split(":", 1)[-1].lstrip("/")
                        r = subprocess.run(
                            ["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "python3", wsl_script, wsl_path],
                            capture_output=True, text=True, timeout=60)
                        try:
                            return self._send(200, json.loads(r.stdout.strip() or "{}"))
                        except Exception:
                            return self._send(200, {"status": "ERROR", "err": (r.stdout or r.stderr)[-200:]})
                return self._send(404, {"error": "not found"})
            return self._send(404, {"error": "no such endpoint"})
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"demo: http://127.0.0.1:{port}", flush=True)
    print(f"  nodes  : {len(load_details())} 配置", flush=True)
    print(f"  probe  : {_cache.get('probe_src')}", flush=True)
    print(f"  pool   : {POOL_STATE}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
