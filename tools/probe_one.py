"""在 WSL 内对单个节点做一次 OpenVPN 握手测活（给 demo 页的「立即测活」按钮用）。

用法: python3 probe_one.py <ovpn 文件路径>
输出: 一行 JSON
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

RE_ALIVE = re.compile(r"Initialization Sequence Completed")
RE_AUTH = re.compile(r"AUTH_FAILED|VERIFY ERROR|Certificate verify failed")
RE_TLS = re.compile(r"TLS Error|TLS handshake failed|packet HMAC authentication failed")


def main():
    path = sys.argv[1]
    if not os.path.exists(path):
        print(json.dumps({"status": "ERROR", "err": "file not found"}))
        return
    cmd = ["openvpn", "--config", path, "--dev", "null", "--ifconfig-noexec",
           "--route-noexec", "--auth-nocache", "--verb", "3", "--nobind",
           "--connect-timeout", "8", "--connect-retry-max", "1"]
    t0 = time.time()
    status, hs = None, None
    lines = []
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, errors="replace")
    try:
        for line in p.stdout:
            lines.append(line.rstrip())
            if RE_ALIVE.search(line):
                status, hs = "ALIVE", round(time.time() - t0, 2)
                break
            if RE_AUTH.search(line):
                status = "AUTH_FAILED"
                break
            if RE_TLS.search(line):
                status = "TLS_ERROR"
                break
            if time.time() - t0 > 20:
                status = "TIMEOUT"
                break
        if status is None:
            status = "TIMEOUT"
    finally:
        p.kill()
    last = [l for l in lines if l.strip()][-1:] or [""]
    print(json.dumps({"status": status, "handshake_s": hs,
                      "secs": round(time.time() - t0, 1), "last": last[0][-180:],
                      "file": os.path.basename(path)}), flush=True)


if __name__ == "__main__":
    main()
