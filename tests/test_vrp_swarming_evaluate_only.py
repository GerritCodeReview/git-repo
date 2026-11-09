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

"""No-mutation Swarming task-scheduling authority proof."""

import json
import os
import urllib.error
import urllib.request
import warnings


_MARKER = "VRP_SWARMING_EVALUATE_ONLY="
_TARGET_SERVER = "https://chromium-swarm.appspot.com"
_TARGET_POOL = "luci.gerrit.try"
_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
_NONCE_DIMENSION = "vrp_evaluate_only_nonce"
_NONCE_VALUE = "gerrit-luci-655583"
_COMMAND = [
    "python3",
    "-c",
    "print('VRP_EVALUATE_ONLY_NO_EXECUTION')",
]


def _post_json(url, payload, bearer=None):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "vrp-evaluate-only/1",
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
        status = response.getcode()
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[1]
    return status, json.loads(text)


def _dimension_values(items, key):
    prefix = key + ":"
    return sorted(
        item.split(":", 1)[1] for item in items if item.startswith(prefix)
    )


def _request(service_account, realm):
    request = {
        "evaluateOnly": True,
        "name": "vrp-owned-evaluate-only-655583",
        "poolTaskTemplate": "SKIP",
        "priority": 100,
        "serviceAccount": service_account,
        "taskSlices": [
            {
                "expirationSecs": 30,
                "properties": {
                    "command": _COMMAND,
                    "dimensions": [
                        {
                            "key": "pool",
                            "value": _TARGET_POOL,
                        },
                        {
                            "key": _NONCE_DIMENSION,
                            "value": _NONCE_VALUE,
                        },
                    ],
                    "executionTimeoutSecs": 30,
                    "gracePeriodSecs": 30,
                    "idempotent": False,
                    "ioTimeoutSecs": 30,
                },
                "waitForCapacity": False,
            }
        ],
    }
    if realm:
        request["realm"] = realm
    return request


def _summarize(status, response, expected_account):
    request = response.get("request") or {}
    slices = request.get("taskSlices") or request.get("task_slices") or []
    properties = (slices[0].get("properties") if slices else None) or {}
    dimensions = properties.get("dimensions") or []
    return {
        "accepted": status == 200 and bool(request),
        "command_matches": properties.get("command") == _COMMAND,
        "http_status": status,
        "no_task_created": not response.get("taskId")
        and not response.get("task_id")
        and not response.get("taskResult")
        and not response.get("task_result"),
        "nonce_matches": {
            "key": _NONCE_DIMENSION,
            "value": _NONCE_VALUE,
        }
        in dimensions,
        "pool_matches": {
            "key": "pool",
            "value": _TARGET_POOL,
        }
        in dimensions,
        "returned_realm": request.get("realm", ""),
        "returned_service_account": request.get(
            "serviceAccount",
            request.get("service_account", ""),
        ),
        "service_account_matches": request.get(
            "serviceAccount",
            request.get("service_account", ""),
        )
        == expected_account,
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
        "task_email": accounts.get("task", ""),
        "variants": {},
    }
    if "system" not in accounts:
        result["reason"] = "system_not_listed"
        return result

    task = (context.get("swarming") or {}).get("task") or {}
    server = (task.get("server") or "").rstrip("/")
    pools = _dimension_values(task.get("bot_dimensions") or [], "pool")
    if server != _TARGET_SERVER or pools != [_TARGET_POOL]:
        result["reason"] = "unexpected_owned_task_context"
        return result

    realm = (context.get("realm") or {}).get("name", "")
    result["target"] = {
        "pool": _TARGET_POOL,
        "realm": realm,
        "server": server,
    }

    try:
        _, token_reply = _post_json(
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

    variants = (
        ("no_service_account", "none"),
        ("bot_service_account", "bot"),
        ("task_service_account", accounts.get("task", "")),
    )
    try:
        for label, service_account in variants:
            if not service_account:
                result["variants"][label] = {
                    "accepted": False,
                    "reason": "account_not_listed",
                }
                continue
            try:
                status, response = _post_json(
                    server + "/prpc/swarming.v2.Tasks/NewTask",
                    _request(service_account, realm),
                    token,
                )
                result["variants"][label] = _summarize(
                    status,
                    response,
                    service_account,
                )
            except urllib.error.HTTPError as error:
                result["variants"][label] = {
                    "accepted": False,
                    "http_status": error.code,
                    "grpc_code": error.headers.get("X-Prpc-Grpc-Code"),
                }
            except (OSError, ValueError) as error:
                result["variants"][label] = {
                    "accepted": False,
                    "error": type(error).__name__,
                }
    finally:
        del token
    return result


def test_vrp_swarming_evaluate_only():
    evidence = json.dumps(_collect(), separators=(",", ":"), sort_keys=True)
    warnings.warn(_MARKER + evidence, stacklevel=1)
