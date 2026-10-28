import urllib.request, urllib.error, json, time
from concurrent.futures import ThreadPoolExecutor

BASE = "https://site40.mobilejumps.org/public/api/"
H = {"User-Agent": "Dart/3.5 (dart:io)", "Accept": "*/*"}
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

d = json.load(open("recon/allservers.json", encoding="utf-8"))
slug = d["data"][0]["slug"]
print("slug:", slug)


def probe(path, method="GET"):
    url = BASE + path
    req = urllib.request.Request(url, headers=H, method=method)
    try:
        r = op.open(req, timeout=25)
        b = r.read(600)
        return path, method, r.status, b
    except urllib.error.HTTPError as e:
        return path, method, e.code, b""
    except Exception as e:
        return path, method, type(e).__name__, b""


pats = []
kinds = ["server", "servers", "connect", "config", "configs", "ovpn", "owpn", "openvpn",
         "wg", "wireguard", "tunnel", "detail", "details", "get", "fetch", "serverconfig",
         "serverconfigs", "download", "profile", "info", "node", "id"]
for k in kinds:
    pats.append(f"{k}/{slug}")
    pats.append(f"{slug}")
    pats.append(f"{k}?slug={slug}")
    pats.append(f"{k}?id={d['data'][0]['id']}")
pats += [f"?slug={slug}", f"allservers/{slug}", f"allservers/{d['data'][0]['id']}"]
pats = list(dict.fromkeys(pats))


def run(p):
    return probe(p)


hits = []
t0 = time.time()
with ThreadPoolExecutor(max_workers=6) as ex:
    for path, method, status, body in ex.map(run, pats):
        if status in (404, 403):
            continue
        print(f"RES {path} {method} -> {status} {body[:300]!r}", flush=True)
        hits.append((path, method, status, body))
print(f"done {time.time()-t0:.0f}s hits={len(hits)}")
json.dump([{"path": p, "status": s, "body": b.decode("utf-8", "replace")} for p, m, s, b in hits],
          open("recon/slug_hits.json", "w", encoding="utf-8"), indent=1)
