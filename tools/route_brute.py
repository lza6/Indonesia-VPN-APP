import urllib.request, urllib.error, itertools, json, sys, time
from concurrent.futures import ThreadPoolExecutor

BASE = "https://site40.mobilejumps.org/public/api/"
H = {"User-Agent": "Dart/3.5 (dart:io)", "Accept": "*/*"}
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(path, method="GET"):
    url = BASE + path
    req = urllib.request.Request(url, headers=H, method=method)
    try:
        r = op.open(req, timeout=20)
        body = r.read(300)
        return path, method, r.status, body[:200]
    except urllib.error.HTTPError as e:
        return path, method, e.code, b""
    except Exception as e:
        return path, method, type(e).__name__, b""


def build_wordlist():
    core = """server servers serverlist node nodes vpn vpns config configs country countries
    region regions list get data free premium tunnel tunnels ovpn owpn openvpn wire wireguard wg
    proxy proxies ip ips connect start stop usage status info app apps client clients user users
    auth login register device devices token sub subscription subs link links version update check
    ping test time ad ads setting settings plan plans price order purchase verify receipt referral
    share notice notices banner banners menu home init bootstrap meta cdn static upload geo geoip
    location locations city cities citylist ovpnlist owpnlist servervpn daftar akun gratis kuota
    all allservers best bestserver random randomserver premiumservers freeservers vpnservers
    serverlist2 getserver getservers getserverlist listserver serverdata vpndata vpnlist vpnconfig""".split()
    cands = set()
    for c in core:
        cands.add(c)
        for p in ("v1/", "v2/", "v3/", "api/"):
            cands.add(p + c)
    pairs = ["server_list", "server-list", "get_server", "get_servers", "list_server",
             "list_servers", "server_list.json", "servers.json", "server.json", "vpn_list",
             "vpn-list", "vpn_servers", "free_servers", "premium_servers", "owpn_servers",
             "ovpn_servers", "get_server_list", "serverlist.json", "v1/server_list",
             "v2/server_list", "v1/servers", "v2/servers", "server/index", "servers/index",
             "server/all", "app/config", "config/app", "user/info", "user/me", "user/profile",
             "device/register", "register/device", "api/server_list", "api/servers"]
    cands.update(pairs)
    return sorted(cands)


def main():
    wl = build_wordlist()
    print(f"probe count={len(wl)}", flush=True)
    hits, errs = [], []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        for path, method, status, body in ex.map(probe, wl):
            if status in (404, 403):
                continue
            if isinstance(status, str):
                errs.append((path, status))
                continue
            hits.append((path, method, status, body))
            print(f"HIT {path} {method} -> {status} {body!r}", flush=True)
    print(f"done in {time.time()-t0:.0f}s hits={len(hits)} errs={len(errs)}")
    json.dump([{"path": p, "method": m, "status": s, "body": b.decode("utf-8", "replace")} for p, m, s, b in hits],
              open("recon/route_hits.json", "w", encoding="utf-8"), indent=1)
    if errs:
        print("ERR sample:", errs[:10])


if __name__ == "__main__":
    main()
