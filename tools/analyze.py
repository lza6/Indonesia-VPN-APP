"""对收割到的 1104 份 .ovpn 做结构与凭证生命周期分析。

输出 output/analysis.json + 控制台摘要。
"""
import glob
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime

WORK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(WORK, "output", "ovpn")
OUT = os.path.join(WORK, "output", "analysis.json")


def parse(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    d = {"file": os.path.basename(path)}
    m = re.search(r"^remote\s+(\S+)\s+(\d+)", txt, re.M)
    d["remote"] = m.group(1) if m else None
    d["port"] = int(m.group(2)) if m else None
    d["proto"] = (re.search(r"^proto\s+(\S+)", txt, re.M) or [None, None])[1]
    d["cipher"] = (re.search(r"^cipher\s+(\S+)", txt, re.M) or [None, None])[1]
    d["auth"] = (re.search(r"^auth\s+(\S+)", txt, re.M) or [None, None])[1]
    d["tls_min"] = (re.search(r"^tls-version-min\s+(\S+)", txt, re.M) or [None, None])[1]
    d["verify_name"] = (re.search(r"^verify-x509-name\s+(\S+)", txt, re.M) or [None, None])[1]
    d["has_tls_crypt"] = "<tls-crypt>" in txt
    d["has_key"] = "<key>" in txt
    d["has_auth_user_pass"] = "auth-user-pass" in txt
    # 各段哈希（判断凭证是否复用）
    for tag in ("ca", "cert", "key", "tls-crypt"):
        mm = re.search(rf"<{tag}>(.*?)</{tag}>", txt, re.S)
        d[f"{tag}_sha"] = hashlib.sha256(mm.group(1).strip().encode()).hexdigest()[:16] if mm else None
    # 证书有效期（从 cert 段的文本 dump 里读）
    cert = (re.search(r"<cert>(.*?)</cert>", txt, re.S) or [None, ""])[1]
    nb = re.search(r"Not Before\s*:\s*(\w{3}\s+\d+\s+[\d:]+\s+\d{4})", cert)
    na = re.search(r"Not After\s*:\s*(\w{3}\s+\d+\s+[\d:]+\s+\d{4})", cert)
    d["not_before"] = nb.group(1) if nb else None
    d["not_after"] = na.group(1) if na else None
    subj = re.search(r"Subject:\s*CN\s*=\s*(\S+)", cert)
    d["subject_cn"] = subj.group(1) if subj else None
    srl = re.search(r"Serial Number:\s*\n?\s*([0-9a-f:]+)", cert)
    d["serial"] = srl.group(1) if srl else None
    return d


def main():
    files = sorted(glob.glob(os.path.join(CFG, "*.ovpn")))
    rows = [parse(f) for f in files]
    countries = Counter(f.split("_")[1] for f in (os.path.basename(x["file"]) for x in rows) if "_" in f)
    ips = [r["remote"] for r in rows if r["remote"]]
    uniq_ips = set(ips)
    exp = Counter((r["not_after"] or "?")[:11] for r in rows)
    ports = Counter(r["port"] for r in rows)
    protos = Counter(r["proto"] for r in rows)
    ciphers = Counter(r["cipher"] for r in rows)
    reuse_ca = Counter(r["ca_sha"] for r in rows)
    reuse_key = Counter(r["key_sha"] for r in rows)
    reuse_tc = Counter(r["tls-crypt_sha"] for r in rows)
    summary = {
        "configs": len(rows),
        "unique_remote_ips": len(uniq_ips),
        "ip_shared_by_multiple_configs": sum(1 for ip, c in Counter(ips).items() if c > 1),
        "top_shared_ips": Counter(ips).most_common(8),
        "ports": dict(ports),
        "protos": dict(protos),
        "ciphers": dict(ciphers),
        "countries": len(countries),
        "top_countries": countries.most_common(12),
        "cert_not_after": exp.most_common(10),
        "unique_ca": len(reuse_ca),
        "unique_client_key": len(reuse_key),
        "unique_tls_crypt": len(reuse_tc),
        "has_key_inline": sum(1 for r in rows if r["has_key"]),
        "has_tls_crypt": sum(1 for r in rows if r["has_tls_crypt"]),
        "needs_user_pass": sum(1 for r in rows if r["has_auth_user_pass"]),
        "subject_cn_sample": [r["subject_cn"] for r in rows[:5]],
        "tls_min": dict(Counter(r["tls_min"] for r in rows)),
    }
    json.dump({"summary": summary, "rows": rows}, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
