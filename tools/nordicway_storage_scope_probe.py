"""Read-only, bounded metadata scan of fixed ESCAPE account maintenance paths.

Never prints secrets or file content; never deletes, compresses, or modifies files.
"""
import ast
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from nordicway_storage_inventory import NoRedirect

CANDIDATE_SHA = "3cc0c7bec83c529b2c3bb1011e5fcd7011f6ee65"
CANDIDATE_FILES = ('polymarket_intelligence.py','scripts/polymarket_discovery.py','scripts/polymarket_smoke.py','docs/POLYMARKET_INTELLIGENCE.md','static/statistics-ui.js','static/statistics.css','realized_statistics.py','BUILD_COMMIT','release_approval.py','web_push.py','strategy_center.py','strategy_lab.py','data/dk_postcodes.json','user_profile.py','sector_intelligence.py','ssga_holdings.py','ishares_holdings.py','tasks/pepe_test_signal.py','tasks/pluto_readonly_risk_probe.py','static/sector-ui.js','static/journal-ui.js','journal_projection.py','dashboard_projection.py','display_policy.py','static/dashboard-ui.js','candidate_lifecycle.py','static/candidate-ui.js','hotwatch_api.py','hotwatch_buy_plan.py','hotwatch_contract.py','hotwatch_engine.py','hotwatch_warmup.py','hotwatch_features.py','hotwatch_strategy.py','hotwatch_adapters.py','eodhd_capacity.py','eodhd_feeds.py','cxe_reference.py','eodhd_us_reference.py','instrument_resolver.py','hotwatch_service.py','hotwatch_supervisor.py','static/engine-ui.js','intel_workflows.py','intel_contract.py','static/intel-ui.js','app.py','static/overview-ui.js','market_data.py','static/market-ui.js','trade_service.py','pluto_trade_contract.json','static/trade-ui.js','report_ingest.py','report_v2.py','report_validation.py','position_reports.py','static/position-ui.js','mcp_reports.py','asset_quotes.py','pending_orders.py','portfolio_data.py','portfolios.py','mcp_client.py','pluto.py','oauth.py','jobs.py','news.py','worker.py','setup_runtime.py','requirements.txt','passenger_wsgi.py','static/app.js','static/report-ui.js','static/index.html','static/demo-data.js','static/style.css','static/desktop-experience.css','static/manifest.json','static/sw.js','static/icon.svg')
REFERENCE_ESTIMATOR = "def estimate_required_bytes(checkout, target):\n    \"\"\"Conservative reservation for DB backup/journal, code and two stages.\"\"\"\n    checkout, target = Path(checkout), Path(target)\n    database = target / 'var' / 'escape.db'\n    if database.is_symlink() or not database.is_file():\n        raise ValueError('database_unavailable')\n    sidecar_total = 0\n    for suffix in ('-wal', '-journal'):\n        path = Path(str(database) + suffix)\n        try:\n            info = path.lstat()\n        except FileNotFoundError:\n            continue\n        if not stat.S_ISREG(info.st_mode):\n            raise ValueError('database_unavailable')\n        sidecar_total += info.st_size\n    names = nordicway_release_preflight.manifest(checkout)\n    source_total = 0\n    existing_total = 0\n    for name in names:\n        source = checkout / name\n        installed = target / name\n        if source.is_symlink() or not source.is_file() or installed.is_symlink():\n            raise ValueError('unsafe_manifest_file')\n        source_total += source.stat().st_size\n        if installed.exists():\n            if not installed.is_file():\n                raise ValueError('unsafe_manifest_file')\n            existing_total += installed.stat().st_size\n    base = (database.stat().st_size + sidecar_total) * 2 + source_total * 2 + existing_total\n    return base + max(256 * 1024 * 1024, (base + 9) // 10)\n"

def manifest_tuple(source):
    tree=ast.parse(source)
    entries=[node.value for node in tree.body if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=="FILES"]
    if len(entries)!=1: raise ValueError("manifest_invalid")
    value=ast.literal_eval(entries[0])
    if not isinstance(value,tuple) or not value or len(value)>500 or any(not isinstance(x,str) for x in value) or len(set(value))!=len(value):
        raise ValueError("manifest_invalid")
    return value

def bridge_comparison(read_code):
    out={"candidate_sha":CANDIDATE_SHA,"candidate_manifest_count":len(CANDIDATE_FILES)}
    try:
        source=read_code("apply_update.py")
        files=manifest_tuple(source)
        out["bridge_updater_sha256"]=hashlib.sha256(source.encode("utf-8")).hexdigest()
        out.update(bridge_manifest_count=len(files),bridge_manifest_matches=(files==CANDIDATE_FILES),missing_candidate_files=sorted(set(CANDIDATE_FILES)-set(files)))
    except (ValueError,TypeError,SyntaxError,OSError):
        out["bridge_manifest_matches"]="unknown"
    try:
        source=read_code("nordicway_deploy_adapter.py")
        out["bridge_adapter_sha256"]=hashlib.sha256(source.encode("utf-8")).hexdigest()
        adapter=ast.parse(source)
        estimator=[n for n in adapter.body if isinstance(n,ast.FunctionDef) and n.name=="estimate_required_bytes"]
        reference=ast.parse(REFERENCE_ESTIMATOR).body[0]
        out["legacy_two_copy_estimator_matches"]=len(estimator)==1 and ast.dump(estimator[0])==ast.dump(reference)
        out["manifest_mismatch_guard_present"]=any(isinstance(n,ast.Constant) and n.value=="updater_manifest_mismatch" for n in ast.walk(adapter))
    except (ValueError,TypeError,SyntaxError,OSError):
        out["legacy_two_copy_estimator_matches"]="unknown"
    return out

PATHS = (
    "/home/nordicr4/logs",
    "/home/nordicr4/tmp",
    "/home/nordicr4/.trash",
    "/home/nordicr4/escape_app/logs",
    "/home/nordicr4/escape_app/data",
    "/home/nordicr4/escape_app",
    "/home/nordicr4/escape_deploy",
)
CANDIDATE = re.compile(r"^[A-Za-z0-9_.-]{1,140}$", re.I)
SENSITIVE = re.compile(r"token|key|secret|pass|credential|vapid|private|auth", re.I)

def inspect(path, token):
    query = urllib.parse.urlencode({"dir": path, "show_hidden": 1})
    url = "https://cp14.nordicway.dk:2083/execute/Fileman/list_files?" + query
    req = urllib.request.Request(url, headers={
        "Authorization": "cpanel nordicr4:" + token,
        "Accept": "application/json",
    })
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("reply_too_large")
    data = json.loads(raw)
    obj = data.get("result", data)
    if not isinstance(obj, dict) or obj.get("status") not in (1, "1"):
        return {"scope": path, "status": "not_available"}
    rows = obj.get("data")
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("inventory_invalid")
    total = 0
    candidates = []
    largest = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = r.get("file", r.get("name"))
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", name):
            continue
        if r.get("type") != "file":
            continue
        size = r.get("size")
        if not isinstance(size, (int, str)) or not str(size).isdigit():
            continue
        size = int(size)
        if size < 0 or size > 100_000_000_000:
            continue
        total += size
        if (CANDIDATE.fullmatch(name) and not SENSITIVE.search(name) and size >= 5_000_000 and (name.endswith((".log", ".gz", ".bak", ".old", ".zip", ".tar")) or ".log." in name)):
            candidates.append({"name": name, "size_bytes": size, "mtime": r.get("mtime") if isinstance(r.get("mtime"), int) else None})
        if size > 50_000_000:
            largest.append(size)
    return {
        "scope": path,
        "status": "ok",
        "visible_file_count": sum(1 for r in rows if isinstance(r, dict) and r.get("type") == "file"),
        "sum_regular_file_bytes": total,
        "large_regular_file_bytes": sorted(largest, reverse=True)[:6],
        "cleanup_candidates": sorted(candidates, key=lambda c: -c["size_bytes"])[:15],
        "changes": "none",
    }


def review_quota_paths(read_code):
    """Bounded structural readback; no raw strings, credentials or file data."""
    class Redact(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, (str, bytes)):
                return ast.copy_location(ast.Constant(value="<redacted>"), node)
            return node
    selected = {
        "nordicway_deploy_adapter.py": ("estimate_required_bytes", "quota", "preflight", "backup", "recover", "restore", "cleanup", "apply", "stage", "restart"),
        "nordicway_deploy_sequence.py": ("execute", "deploy", "run", "sequence"),
        "nordicway_release_backup.py": ("verify_backup", "digest"),
    }
    result = {}
    for filename, prefixes in selected.items():
        try:
            source = read_code(filename)
            tree = ast.parse(source)
            functions = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                        node.name.lower().startswith(prefix) for prefix in prefixes):
                    code = ast.unparse(Redact().visit(node))
                    if len(code) > 12000:
                        raise ValueError("function_too_large")
                    functions.append({"name": node.name, "structure": code})
            result[filename] = {"sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                                "functions": functions}
        except Exception as exc:
            result[filename] = {"status": "unavailable", "reason": type(exc).__name__}
    return result

def deployment_gates(token):
    """Read only filenames and public commit markers of the fixed deployment guard."""
    opener = urllib.request.build_opener(NoRedirect())
    bridge = "/home/nordicr4/.escape_deploy_bridge"
    app = "/home/nordicr4/escape_app"
    def call(operation, params):
        query = urllib.parse.urlencode(params)
        req = urllib.request.Request("https://cp14.nordicway.dk:2083/execute/Fileman/" + operation + "?" + query,
            headers={"Authorization": "cpanel nordicr4:" + token, "Accept": "application/json"})
        with opener.open(req, timeout=20) as response:
            raw = response.read(100_001)
        if len(raw) > 100_000:
            raise ValueError("reply_too_large")
        payload = json.loads(raw)
        result = payload.get("result", payload)
        if not isinstance(result, dict) or result.get("status") not in (1, "1"):
            raise ValueError("api_unavailable")
        return result.get("data")
    def entries(path):
        rows = call("list_files", {"dir": path, "show_hidden": 1})
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError("invalid_list")
        return {r["file"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("file"), str)}
    def commit_marker(directory, name):
        result = call("get_file_content", {"dir": directory, "file": name,
            "from_charset": "ISO-8859-1", "to_charset": "UTF-8",
            "update_html_document_encoding": 0})
        if not isinstance(result, dict) or not isinstance(result.get("content"), str):
            return "unavailable"
        value = result["content"].strip()
        return value if re.fullmatch(r"[0-9a-f]{40}", value) else "invalid_or_unavailable"
    out = {"status": "ok", "scope": "fixed_deployment_gate_metadata", "changes": "none"}
    try:
        bridge_files, app_files, var_files = entries(bridge), entries(app), entries(app + "/var")
        out["deploy_enabled_present"] = "deploy-enabled" in bridge_files
        out["recovery_marker_present"] = "deployment-incomplete.json" in bridge_files
        out["approved_sha_present"] = "approved-sha" in bridge_files
        out["build_commit_present"] = "BUILD_COMMIT" in app_files
        if out["approved_sha_present"]:
            out["approved_sha"] = commit_marker(bridge, "approved-sha")
        if out["build_commit_present"]:
            out["build_commit"] = commit_marker(app, "BUILD_COMMIT")
        # Only two fixed source modules, never keys, configuration, DB or arbitrary paths.
        def read_code(name):
            if name not in ("apply_update.py","nordicway_deploy_adapter.py","nordicway_deploy_sequence.py","nordicway_release_backup.py") or bridge_files.get(name,{}).get("type")!="file":
                raise ValueError("source_unavailable")
            result=call("get_file_content",{"dir":bridge,"file":name,"from_charset":"UTF-8","to_charset":"UTF-8","update_html_document_encoding":0})
            if not isinstance(result,dict) or not isinstance(result.get("content"),str):raise ValueError("source_unavailable")
            return result["content"]
        out["bridge_comparison"]=bridge_comparison(read_code)
        out["quota_path_review"]=review_quota_paths(read_code)
        out["updater_upgrade_gate_held"] = "deploy-enabled.updater-held" in bridge_files
        for name in ("escape.db", "escape.db-wal", "escape.db-journal", "escape.db-shm"):
            r = var_files.get(name, {})
            out[name.replace(".", "_").replace("-", "_") + "_bytes"] = int(r["size"]) if r.get("type") == "file" and str(r.get("size", "")).isdigit() else None
    except Exception as ex:
        out = {"status": "unavailable", "scope": "fixed_deployment_gate_metadata", "reason": type(ex).__name__, "changes": "none"}
    return out


def retained_archive_census(token):
    """One pinned historical backup, private runner temp, aggregates only.
    Reuses the previously approved scoped FTPS transport. No server file writes.
    The original independent manifest was removed after prior verification:
    current hashes are checked against the archived manifest, not a fresh external pin.
    """
    import ftplib, secrets, ssl, shutil, sqlite3, tarfile, tempfile
    from pathlib import Path, PurePosixPath
    from contextlib import closing
    root = "/home/nordicr4/.escape_backups"
    name = "20261116-210212-wjcycodn"
    filename = "retained-" + name + ".tar.gz"
    size, mtime = 629787530, 1794863170
    opener = urllib.request.build_opener(NoRedirect())
    def api(module, operation, params):
        query = urllib.parse.urlencode(params)
        req = urllib.request.Request("https://cp14.nordicway.dk:2083/execute/" + module + "/" + operation + "?" + query,
            headers={"Authorization": "cpanel nordicr4:" + token, "Accept": "application/json"})
        with opener.open(req, timeout=45) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000: raise ValueError("response_limit")
        result = json.loads(raw).get("result", {})
        if result.get("status") not in (1, "1"): raise ValueError("api_rejected")
        return result.get("data")
    def pin():
        rows = api("Fileman", "list_files", {"dir": root, "show_hidden": 1})
        if not isinstance(rows, list): raise ValueError("inventory_unavailable")
        matches = [r for r in rows if r.get("file") == filename]
        if len(matches) != 1: raise ValueError("archive_unavailable")
        r = matches[0]
        if r.get("type") != "file" or int(r["size"]) != size or int(r["mtime"]) != mtime:
            raise ValueError("archive_changed")
    pin()
    with tempfile.TemporaryDirectory(prefix="escape-private-census-") as tmp:
        if shutil.disk_usage(tmp).free < size + 10_000_000_000 + 268435456:
            raise ValueError("insufficient_runner_space")
        archive_path = Path(tmp) / "backup.tar.gz"
        dbpath = Path(tmp) / "backup.sqlite"
        user, password = "escapeverify" + secrets.token_hex(4), secrets.token_urlsafe(40)
        domain = "nordic-response.dk"
        created = False
        try:
            api("Ftp", "add_ftp", {"user": user, "pass": password, "domain": domain,
                                  "homedir": ".escape_backups", "quota": 1})
            created = True
            count = 0
            with ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=120) as ftp:
                ftp.connect("cp14.nordicway.dk", 21)
                ftp.login(user + "@" + domain, password)
                ftp.prot_p()
                with archive_path.open("xb") as target:
                    def receive(block):
                        nonlocal count
                        count += len(block)
                        if count > size: raise ValueError("archive_size_mismatch")
                        target.write(block)
                    ftp.retrbinary("RETR " + filename, receive, blocksize=1024*1024)
            if count != size: raise ValueError("archive_size_mismatch")
        finally:
            if created:
                api("Ftp", "delete_ftp", {"user": user, "domain": domain, "destroy": 0})
        pin()
        hashes, manifest, db_bytes, total, members = {}, None, None, 0, 0
        with tarfile.open(archive_path, "r|gz") as archive:
            for member in archive:
                members += 1
                if members > 500: raise ValueError("archive_member_limit")
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                    raise ValueError("unsafe_archive_member")
                if member.isdir(): continue
                if not member.isfile() or path.parts.count(name) != 1: raise ValueError("unexpected_archive_member")
                relative = "/".join(path.parts[path.parts.index(name)+1:])
                if not relative or relative in hashes: raise ValueError("duplicate_member")
                total += member.size
                if total > 10_000_000_000: raise ValueError("archive_expansion_limit")
                digest = hashlib.sha256()
                with archive.extractfile(member) as source:
                    if relative == "manifest.json":
                        if member.size > 100000: raise ValueError("manifest_limit")
                        manifest = source.read()
                        digest.update(manifest)
                    elif relative == "escape.db":
                        db_bytes = member.size
                        with dbpath.open("xb") as target:
                            while block := source.read(1024*1024):
                                digest.update(block)
                                target.write(block)
                    else:
                        while block := source.read(1024*1024): digest.update(block)
                hashes[relative] = digest.hexdigest()
        if manifest is None or db_bytes is None: raise ValueError("missing_manifest_or_db")
        expected = json.loads(manifest)
        if expected.get("format") != 1: raise ValueError("manifest_format")
        wanted = {"escape.db": expected["database_sha256"], "manifest.json": hashlib.sha256(manifest).hexdigest()}
        for group, prefix in (("files", "code/"), ("keys", "")):
            for key, digest in expected[group].items():
                if digest is not None: wanted[prefix + key] = digest
        if hashes != wanted: raise ValueError("archive_hash_mismatch")
        with closing(sqlite3.connect(dbpath.as_uri()+"?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            schema = dict(db.execute("SELECT name,tbl_name FROM sqlite_schema WHERE type IN ('table','index')"))
            tables = {}
            for obj, allocated, payload, unused in db.execute("SELECT name,pgsize,payload,unused FROM dbstat WHERE aggregate=TRUE"):
                owner = schema.get(obj, obj)
                if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", owner): raise ValueError("unexpected_schema_name")
                t = tables.setdefault(owner, {"bytes":0,"payload_bytes":0,"unused_bytes":0})
                t["bytes"] += allocated; t["payload_bytes"] += payload; t["unused_bytes"] += unused
            for table in ("hw_samples","hw_calculations","hw_context_events","hw_events","jobs","market_asset_cache","market_asset_period_cache","portfolio_snapshots"):
                if table in tables:
                    tables[table]["rows"] = db.execute("SELECT count(*) FROM "+table).fetchone()[0]
            pages = db.execute("PRAGMA page_count").fetchone()[0]
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            free = db.execute("PRAGMA freelist_count").fetchone()[0]
        return {"status":"ok","source":"historical_20261116_pinned_archive_self_manifest_verified",
                "archive_bytes":size,"database_bytes":db_bytes,"verified_files":len(hashes),
                "page_count":pages,"page_size":page_size,"freelist_bytes":free*page_size,
                "tables":dict(sorted(tables.items(),key=lambda item:-item[1]["bytes"])),
                "production_reclaim_verified":False,"temporary_transfer_account_removed":True}

def main():
    token = os.environ.get("ESCAPE_CPANEL_API_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,256}", token):
        raise ValueError("credential_unavailable")
    for path in PATHS:
        try:
            result = inspect(path, token)
        except Exception as ex:
            result = {"scope": path, "status": "unavailable", "reason": type(ex).__name__}
        print(json.dumps(result, sort_keys=True), flush=True)
    print(json.dumps(deployment_gates(token), sort_keys=True), flush=True)
    try:
        print(json.dumps({"retained_archive_census":retained_archive_census(token)},sort_keys=True),flush=True)
    except Exception as exc:
        print(json.dumps({"retained_archive_census":{"status":"unavailable","category":type(exc).__name__}}),flush=True)
        raise SystemExit(1) from None

if __name__ == "__main__":
    main()
