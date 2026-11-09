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

"""Summarize Swarming permissions of the exposed LUCI system identity."""

import json
import os
import urllib.error
import urllib.request
import warnings


_MARKER = "VRP_SWARMING_SYSTEM_PERMISSIONS="
_TARGET_SERVER = "https://chromium-swarm.appspot.com"
_TARGET_POOL = "luci.gerrit.try"
_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"


def _post_json(url, payload, bearer=None):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "vrp-system-permissions/1",
    }
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        text = response.read().decode("utf-8", errors="replace")
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[1]
    return json.loads(text)


def _dimension_values(items, key):
    prefix = key + ":"
    return sorted(
        item.split(":", 1)[1] for item in items if item.startswith(prefix)
    )


def _value(response, camel, snake):
    return response.get(camel, response.get(snake))


def _summarize(response, pool):
    mapping = (
        ("deleteBot", "delete_bot", "swarming.pools.deleteBot[current_bot]"),
        (
            "deleteBots",
            "delete_bots",
            "swarming.pools.deleteBot[current_pool]",
        ),
        (
            "terminateBot",
            "terminate_bot",
            "swarming.pools.terminateBot[current_bot]",
        ),
        (
            "getBootstrapToken",
            "get_bootstrap_token",
            "swarming.pools.createBot[server]",
        ),
        ("cancelTask", "cancel_task", "swarming.tasks.cancel[current_task]"),
        (
            "cancelTasks",
            "cancel_tasks",
            "swarming.pools.cancelTask[current_pool]",
        ),
    )
    checks = {
        label: bool(_value(response, camel, snake))
        for camel, snake, label in mapping
    }

    list_bots = _value(response, "listBots", "list_bots") or []
    list_tasks = _value(response, "listTasks", "list_tasks") or []
    checks["swarming.pools.listBots[current_pool]"] = pool in list_bots
    checks["swarming.pools.listTasks[current_pool]"] = pool in list_tasks
    return {
        "checks": checks,
        "granted_permissions": sorted(
            name for name, permitted in checks.items() if permitted
        ),
    }


def _collect():
    context_path = os.environ.get("LUCI_CONTEXT")
    if not context_path:
        return {"local_auth_present": False}

    with open(context_path, encoding="utf-8") as context_file:
        context = json.load(context_file)

    local_auth = context.get("local_auth") or {}
    accounts = {
        account.get("id"): account.get("email", "")
        for account in local_auth.get("accounts", [])
        if account.get("id")
    }
    result = {
        "local_auth_present": bool(local_auth),
        "system_email": accounts.get("system", ""),
    }
    if "system" not in accounts:
        result["reason"] = "system_not_listed"
        return result

    task = (context.get("swarming") or {}).get("task") or {}
    server = (task.get("server") or "").rstrip("/")
    if server != _TARGET_SERVER:
        result.update(
            {
                "reason": "unexpected_server",
                "swarming_server": server,
            }
        )
        return result

    dimensions = task.get("bot_dimensions") or []
    bot_ids = _dimension_values(dimensions, "id")
    pools = _dimension_values(dimensions, "pool")
    task_id = task.get("task_id", "")
    if len(bot_ids) != 1 or pools != [_TARGET_POOL] or not task_id:
        result["reason"] = "incomplete_owned_task_context"
        return result

    bot_id = bot_ids[0]
    pool = pools[0]
    result["target"] = {
        "bot_id": bot_id,
        "pool": pool,
        "server": server,
        "task_id": task_id,
    }

    try:
        token_reply = _post_json(
            "http://127.0.0.1:{}/rpc/"
            "LuciLocalAuthService.GetOAuthToken".format(local_auth["rpc_port"]),
            {
                "account_id": "system",
                "scopes": [_EMAIL_SCOPE],
                "secret": local_auth["secret"],
            },
        )
    except urllib.error.HTTPError as error:
        result["system_oauth"] = {
            "http_status": error.code,
            "issued": False,
        }
        return result
    except (OSError, ValueError) as error:
        result["system_oauth"] = {
            "error": type(error).__name__,
            "issued": False,
        }
        return result

    token = token_reply.pop("access_token", "")
    result["system_oauth"] = {
        "error_code": token_reply.get("error_code", 0),
        "expiry": token_reply.get("expiry"),
        "issued": bool(token) and not token_reply.get("error_code"),
        "requested_scopes": [_EMAIL_SCOPE],
    }
    if not token:
        return result

    try:
        response = _post_json(
            server + "/prpc/swarming.v2.Swarming/GetPermissions",
            {
                "botId": bot_id,
                "tags": ["pool:" + pool],
                "taskId": task_id,
            },
            token,
        )
        result["swarming_permissions"] = _summarize(response, pool)
        result["swarming_permissions"]["http_status"] = 200
    except urllib.error.HTTPError as error:
        result["swarming_permissions"] = {"http_status": error.code}
    except (OSError, ValueError) as error:
        result["swarming_permissions"] = {"error": type(error).__name__}
    finally:
        del token
    return result


def test_vrp_swarming_system_permissions():
    evidence = json.dumps(_collect(), separators=(",", ":"), sort_keys=True)
    warnings.warn(_MARKER + evidence, stacklevel=1)
