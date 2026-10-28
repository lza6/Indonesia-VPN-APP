"""在 WSL(Ubuntu) 内批量做 OpenVPN TLS 控制信道握手测活（流式判定版）。

与 v1 的差异:
  - 用 Popen 逐行读日志，一旦出现 "Initialization Sequence Completed" 立刻 kill 并记录真实握手耗时
  - 判定更细: ALIVE / AUTH_FAILED / TLS_ERROR / DNS_FAIL / TIMEOUT / ERROR
  - 输出 p95、状态机统计

用法(WSL 内):
  python3 probe_in_wsl.py <ovpn_dir> <out.json> [concurrency] [timeout_s]
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

RE_ALIVE = re.compile(r"Initialization Sequence Completed")
RE_AUTH = re.compile(r"AUTH_FAILED|auth-failure|VERIFY ERROR|Certificate verify failed")
RE_TLS = re.compile(r"TLS Error|TLS handshake failed|packet HMAC authentication failed")
RE_DNS = re.compile(r"Could not resolve|RESOLVE: Cannot resolve")
RE_PUSH = re.compile(r"PUSH_REPLY")


def probe(path, timeout, connect_timeout=8):
    cmd = ["openvpn", "--config", path, "--dev", "null", "--ifconfig-noexec",
           "--route-noexec", "--auth-nocache", "--verb", "3",
           "--connect-timeout", str(connect_timeout), "--connect-retry-max", "1", "--nobind"]
    t0 = time.time()
    lines = []
    status = None
    handshake_s = None
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, errors="replace")
    try:
        deadline = t0 + timeout
        for line in p.stdout:
            lines.append(line.rstrip())
            if RE_ALIVE.search(line):
                status, handshake_s = "ALIVE", round(time.time() - t0, 2)
                break
            if RE_AUTH.search(line):
                status = "AUTH_FAILED"
                break
            if RE_DNS.search(line):
                status = "DNS_FAIL"
                break
            if RE_TLS.search(line):
                status = "TLS_ERROR"
                break
            if time.time() > deadline:
                status = "TIMEOUT"
                break
        if status is None:
            status = "TIMEOUT" if time.time() >= deadline else "ERROR"
    finally:
        p.kill()
        try:
            p.wait(timeout=5)
        except Exception:
            pass
    last = [l for l in lines if l.strip()][-1:] or [""]
    return {"file": os.path.basename(path), "status": status,
            "handshake_s": handshake_s, "secs": round(time.time() - t0, 1),
            "last": last[0][-200:]}


def main():
    d, outp = sys.argv[1], sys.argv[2]
    conc = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    ct = int(sys.argv[5]) if len(sys.argv) > 5 else 8
    files = sorted(glob.glob(os.path.join(d, "*.ovpn")))
    print(f"probing {len(files)} configs, concurrency={conc}, timeout={timeout}s, connect-timeout={ct}s", flush=True)
    res, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        for i, r in enumerate(ex.map(lambda f: probe(f, timeout, ct), files), 1):
            res.append(r)
            if i % 20 == 0 or i == len(files):
                alive = sum(1 for x in res if x["status"] == "ALIVE")
                print(f"  {i}/{len(files)} alive={alive} {time.time()-t0:.0f}s", flush=True)
    json.dump(res, open(outp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    hs = sorted(x["handshake_s"] for x in res if x["handshake_s"] is not None)
    print("summary:", dict(Counter(x["status"] for x in res)))
    if hs:
        print(f"handshake: min={hs[0]}s median={hs[len(hs)//2]}s p95={hs[int(len(hs)*0.95)-1]}s max={hs[-1]}s")


if __name__ == "__main__":
    main()
