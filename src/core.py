"""LAN file-sharing engine for SigmaOS-LAN-fileshare (warpinator, owly).

Principles: plan-before-act (send/receive are pure plans over a manifest),
defensive parsing (no path traversal in manifests, strict peer validation),
integrity via SHA-256 (verify is read-only), fail-fast, deterministic order.
"""
import argparse, hashlib, json, os, re, sys

ENGINE = {
    "name": "sigma-lanshare",
    "summary": "Plan and verify LAN file transfers between trusted peers",
    "language": "python",
    "verbs": ["send-plan", "receive-plan", "peers", "verify"],
    "principles": ["Plan Before Act", "Defensive Programming", "Fail-Fast",
                   "Least Privilege", "KISS", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-lanshare peers peers.conf
alpha   192.168.1.10:8443  key=...
beta    192.168.1.11:8443
$ sigma-lanshare send-plan peers.conf alpha ./trip --files img1.jpg img2.jpg
$ sigma-lanshare receive-plan manifest.json --out ~/Downloads/lanshare
$ sigma-lanshare verify manifest.json ~/Downloads/lanshare
ok=2 missing=0 mismatched=0
"""

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")
_KEY_RE = re.compile(r"^[0-9a-fA-F]{8,128}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ShareError(ValueError):
    pass


def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_peers(text):
    """Parse `name host:port [key=HEX]` lines into a dict keyed by name."""
    peers = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        raw_name = parts[0]
        if not _NAME_RE.match(raw_name):
            raise ShareError(f"line {lineno}: bad peer name {raw_name!r} "
                             f"(use lowercase)")
        name = raw_name.lower()
        if name in peers:
            raise ShareError(f"line {lineno}: duplicate peer {name!r}")
        if len(parts) < 2 or ":" not in parts[1]:
            raise ShareError(f"line {lineno}: expected 'name host:port'")
        host, _, port_s = parts[1].rpartition(":")
        if not host or not port_s.isdigit() or not 1 <= int(port_s) <= 65535:
            raise ShareError(f"line {lineno}: bad endpoint {parts[1]!r}")
        key = None
        for opt in parts[2:]:
            if opt.startswith("key="):
                key = opt[4:]
                if not _KEY_RE.match(key):
                    raise ShareError(f"line {lineno}: bad peer key")
            else:
                raise ShareError(f"line {lineno}: unknown option {opt!r}")
        peers[name] = {"host": host, "port": int(port_s), "key": key}
    if not peers:
        raise ShareError("peer list is empty")
    return dict(sorted(peers.items()))


def send_plan(peers, target, root, files):
    """Pure send plan with a hashed manifest; never opens a socket."""
    if target not in peers:
        raise ShareError(f"unknown peer {target!r} "
                         f"(known: {', '.join(peers) or 'none'})")
    if not files:
        raise ShareError("no files selected")
    root_real = os.path.realpath(root)
    manifest, total = [], 0
    seen = set()
    for rel in files:
        if os.path.isabs(rel) or rel.split("/")[0] == "..":
            raise ShareError(f"refusing unsafe file name {rel!r}")
        full = os.path.realpath(os.path.join(root, rel))
        if os.path.commonpath([full, root_real]) != root_real:
            raise ShareError(f"file escapes share root: {rel!r}")
        if not os.path.isfile(full):
            raise ShareError(f"missing file: {rel!r}")
        base = os.path.basename(rel)
        if base in seen:
            raise ShareError(f"duplicate file name in manifest: {base!r}")
        seen.add(base)
        size = os.path.getsize(full)
        manifest.append({"name": base, "size": size,
                         "sha256": _sha256(full)})
        total += size
    peer = peers[target]
    return {
        "target": target,
        "endpoint": f"{peer['host']}:{peer['port']}",
        "authenticated": peer["key"] is not None,
        "bytes": total,
        "manifest": manifest,
        "steps": [f"connect {peer['host']}:{peer['port']}",
                  "verify peer key" if peer["key"] else "warn: no peer key",
                  f"send manifest ({len(manifest)} file(s), {total} bytes)",
                  "await receiver acknowledgement"],
    }


def validate_manifest(manifest):
    """Reject unsafe or malformed manifest entries (path traversal etc.)."""
    if not manifest:
        raise ShareError("manifest is empty")
    seen = set()
    for entry in manifest:
        name = entry.get("name", "")
        if not name or "/" in name or "\\" in name or name in (".", "..") \
                or "\x00" in name:
            raise ShareError(f"unsafe manifest name: {name!r}")
        if name in seen:
            raise ShareError(f"duplicate manifest name: {name!r}")
        seen.add(name)
        size = entry.get("size")
        if not isinstance(size, int) or size < 0:
            raise ShareError(f"bad size for {name!r}")
        if not _SHA_RE.match(str(entry.get("sha256", ""))):
            raise ShareError(f"bad sha256 for {name!r}")
    return manifest


def receive_plan(manifest, out_dir):
    """Pure receive plan: validate the manifest, lay out the destination."""
    validate_manifest(manifest)
    steps = [f"bind receiver on 0.0.0.0",
             "negotiate protocol, present peer key",
             f"receive manifest ({len(manifest)} file(s))"]
    for entry in sorted(manifest, key=lambda e: e["name"]):
        steps.append(f"receive {entry['name']} "
                     f"({entry['size']} bytes) -> {os.path.join(out_dir, entry['name'])}")
        steps.append(f"sha256 check {entry['name']}")
    steps.append("write receipt.json")
    return {"out_dir": out_dir, "manifest": manifest, "steps": steps}


def verify(manifest, root):
    """Read-only integrity check of received files against the manifest."""
    validate_manifest(manifest)
    report = {"ok": [], "missing": [], "mismatched": []}
    for entry in sorted(manifest, key=lambda e: e["name"]):
        full = os.path.join(root, entry["name"])
        if not os.path.isfile(full):
            report["missing"].append(entry["name"])
        elif _sha256(full) != entry["sha256"]:
            report["mismatched"].append(entry["name"])
        else:
            report["ok"].append(entry["name"])
    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"],
                                description=ENGINE["summary"])
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("peers", help="list known peers")
    pp.add_argument("peers_file")
    sp = sub.add_parser("send-plan", help="plan a transfer to a peer")
    sp.add_argument("peers_file")
    sp.add_argument("target")
    sp.add_argument("root", help="share root directory")
    sp.add_argument("--files", nargs="+", required=True)
    rp = sub.add_parser("receive-plan", help="plan an incoming transfer")
    rp.add_argument("manifest_file")
    rp.add_argument("--out", required=True)
    vf = sub.add_parser("verify", help="verify received files (read-only)")
    vf.add_argument("manifest_file")
    vf.add_argument("root")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "peers":
            for name, peer in parse_peers(_read(args.peers_file)).items():
                key = "key=..." if peer["key"] else "-"
                print(f"{name:<8} {peer['host']}:{peer['port']}  {key}")
            return 0
        if args.cmd == "send-plan":
            peers = parse_peers(_read(args.peers_file))
            plan = send_plan(peers, args.target, args.root, args.files)
            print(f"send {len(plan['manifest'])} file(s), "
                  f"{plan['bytes']} bytes -> {plan['target']} "
                  f"@ {plan['endpoint']}")
            for entry in plan["manifest"]:
                print(f"  {entry['name']}  {entry['size']}  {entry['sha256'][:12]}...")
            return 0
        manifest = json.loads(_read(args.manifest_file))
        manifest = manifest.get("manifest", manifest) \
            if isinstance(manifest, dict) else manifest
        if args.cmd == "receive-plan":
            plan = receive_plan(manifest, args.out)
            print(f"receive {len(plan['manifest'])} file(s) into {plan['out_dir']}")
            for step in plan["steps"]:
                print(f"  {step}")
        elif args.cmd == "verify":
            r = verify(manifest, args.root)
            print(f"ok={len(r['ok'])} missing={len(r['missing'])} "
                  f"mismatched={len(r['mismatched'])}")
            for name in r["missing"]:
                print(f"  MISSING  {name}")
            for name in r["mismatched"]:
                print(f"  BAD-HASH {name}")
            return 1 if (r["missing"] or r["mismatched"]) else 0
        return 0
    except (ShareError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    sample = """\
# trusted peers
alpha 192.168.1.10:8443 key=deadbeefcafe1234
beta 192.168.1.11:8443
"""
    peers = parse_peers(sample)
    assert list(peers) == ["alpha", "beta"]
    assert peers["alpha"]["port"] == 8443 and peers["alpha"]["key"]
    assert peers["beta"]["key"] is None

    for bad in (
        lambda: parse_peers("Alpha 192.168.1.1:1\n"),      # uppercase name
        lambda: parse_peers("a 1.2.3.4:1\na 1.2.3.5:2\n"),  # duplicate
        lambda: parse_peers("a 1.2.3.4\n"),                 # no port
        lambda: parse_peers("a 1.2.3.4:99999\n"),           # bad port
        lambda: parse_peers("a 1.2.3.4:1 key=zz\n"),        # bad key hex
        lambda: parse_peers("a 1.2.3.4:1 extra\n"),         # unknown option
        lambda: parse_peers("# nothing\n"),
    ):
        try:
            bad()
        except ShareError:
            pass
        else:
            raise AssertionError("expected ShareError")

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = os.path.join(d, "trip")
        os.makedirs(root)
        for name, blob in (("img1.jpg", b"JPEGDATA"), ("img2.jpg", b"MORE")):
            with open(os.path.join(root, name), "wb") as fh:
                fh.write(blob)
        with open(os.path.join(root, "notes.txt"), "w") as fh:
            fh.write("not selected")

        plan = send_plan(peers, "alpha", root, ["img1.jpg", "img2.jpg"])
        assert plan["bytes"] == len(b"JPEGDATA") + len(b"MORE")
        assert plan["authenticated"] is True
        assert plan["manifest"][0]["name"] == "img1.jpg"
        assert _SHA_RE.match(plan["manifest"][0]["sha256"])

        for bad in (
            lambda: send_plan(peers, "nobody", root, ["img1.jpg"]),
            lambda: send_plan(peers, "alpha", root, []),
            lambda: send_plan(peers, "alpha", root, ["../etc/hosts"]),
            lambda: send_plan(peers, "alpha", d, ["trip/../escape"]),
            lambda: send_plan(peers, "alpha", root, ["missing.jpg"]),
            lambda: send_plan(peers, "alpha", root, ["img1.jpg", "x/../img1.jpg"]),
        ):
            try:
                bad()
            except ShareError:
                pass
            else:
                raise AssertionError("expected ShareError")

        rplan = receive_plan(plan["manifest"], os.path.join(d, "inbox"))
        assert any("img2.jpg" in s for s in rplan["steps"])
        for bad in (
            lambda: receive_plan([], "/tmp/x"),
            lambda: receive_plan([{"name": "../evil", "size": 1,
                                   "sha256": "a" * 64}], "/tmp/x"),
            lambda: receive_plan([{"name": "/abs", "size": 1,
                                   "sha256": "a" * 64}], "/tmp/x"),
            lambda: receive_plan([{"name": "a", "size": -1,
                                   "sha256": "a" * 64}], "/tmp/x"),
            lambda: receive_plan([{"name": "a", "size": 1,
                                   "sha256": "nothex"}], "/tmp/x"),
            lambda: receive_plan([{"name": "a", "size": 1, "sha256": "a" * 64},
                                  {"name": "a", "size": 2, "sha256": "b" * 64}],
                                 "/tmp/x"),
        ):
            try:
                bad()
            except ShareError:
                pass
            else:
                raise AssertionError("expected ShareError")

        inbox = os.path.join(d, "inbox")
        os.makedirs(inbox)
        for entry in plan["manifest"]:
            src = os.path.join(root, entry["name"])
            with open(os.path.join(inbox, entry["name"]), "wb") as fh:
                fh.write(open(src, "rb").read())
        rep = verify(plan["manifest"], inbox)
        assert rep["ok"] == ["img1.jpg", "img2.jpg"]
        assert rep["missing"] == [] and rep["mismatched"] == []
        # tamper + delete
        with open(os.path.join(inbox, "img1.jpg"), "wb") as fh:
            fh.write(b"TAMPERED")
        os.unlink(os.path.join(inbox, "img2.jpg"))
        rep = verify(plan["manifest"], inbox)
        assert rep["mismatched"] == ["img1.jpg"]
        assert rep["missing"] == ["img2.jpg"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
