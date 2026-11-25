"""Publish only a scoped controller patch as a draft PR; never merge."""
import os
import re
import subprocess
from pathlib import PurePosixPath

class PublicationError(ValueError):
    """Fixed safe reason, never raw agent output."""

REPO = "hva73/invest"
BASES = {"codex/escape-development", "codex/development-controller-pilot", "codex/issue57-combined-release-20261124", "codex/trading-engine-v2-integration"}
# Review-only release fixes, explicitly enumerated. No workflows, runner provisioning,
# credentials, arbitrary tools, or production access.
RELEASE_TOOLS = {"tools/nordicway_app_release.py", "tools/nordicway_deploy_client.py", "tools/nordicway_release_preflight.py", "tools/nordicway_release_retention.py", "tests/test_nordicway_app_release.py", "tests/test_nordicway_deploy_client.py", "tests/test_nordicway_release_preflight.py", "tests/test_nordicway_release_retention.py"}
def allowed(path, scopes, role=None):
    p=PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return False
    if any(x.startswith(".") or x.lower() in ("secrets","credentials","id_rsa") or x.lower().endswith((".pem",".key",".db",".sqlite",".sqlite3")) for x in p.parts):
        return False
    if p.parts[0] in ("tools","scripts","deployment","development") or "deploy" in path.lower():
        return role=="release" and path in RELEASE_TOOLS and path in scopes
    return any(path==s.rstrip("/") or path.startswith(s.rstrip("/")+"/") for s in scopes)

def git(folder,*args):
    return subprocess.check_output(["git","-c","core.hooksPath=/dev/null",*args],cwd=folder,timeout=90)

def commit_scoped(folder,row,branch,base):
    target=row.get("base_branch")
    if (target=="codex/issue57-combined-release-20261124" and row.get("role")!="release") or target not in BASES or not re.fullmatch(r"controller/local-[0-9]+-[0-9]+",branch):
        raise PublicationError("unapproved_branch")
    if git(folder,"rev-parse","HEAD").decode().strip()!=base:
        raise PublicationError("head_changed")
    if git(folder,"branch","--show-current").decode().strip()!=branch:
        raise PublicationError("branch_changed")
    git(folder,"add","-A","--",".")
    names=git(folder,"diff","--cached","--no-renames","--name-only","-z").split(b"\0")
    paths=[os.fsdecode(p) for p in names if p]
    if not paths or len(paths)>30 or not all(allowed(p,row["paths"],row.get("role")) for p in paths):
        raise PublicationError("scope_violation")
    for entry in git(folder,"ls-files","-s","-z").split(b"\0"):
        if entry and entry.split(b" ",1)[0] in (b"120000",b"160000") and os.fsdecode(entry.split(b"\t",1)[1]) in paths:
            raise PublicationError("unsafe_file_type")
    if len(git(folder,"diff","--cached","--binary"))>500000:
        raise PublicationError("patch_too_large")
    git(folder,"-c","user.name=ESCAPE Controller","-c","user.email=controller@users.noreply.github.com","commit","-m",f"Controller draft for #{row['issue']}")
    return git(folder,"rev-parse","HEAD").decode().strip()

def publish(folder,row,branch,base):
    commit_scoped(folder,row,branch,base)
    target=row["base_branch"]
    # Explicit approved destination, no remote configured by agent.
    git(folder,"-c","credential.helper=","-c","credential.helper=!gh auth git-credential","push","https://github.com/"+REPO+".git","HEAD:refs/heads/"+branch)
    return subprocess.check_output(["gh","pr","create","--repo",REPO,"--draft","--base",target,"--head",branch,"--title",f"Controller draft #{row['issue']}","--body",f"Refs #{row['issue']}. Local agent changes; independent review and CI required. No deployment approval."],cwd=folder,text=True,timeout=60).strip()
