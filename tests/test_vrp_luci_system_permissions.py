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

"""Bounded permission proof for the exposed LUCI system identity."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import warnings


_MARKER = "VRP_LUCI_SYSTEM_PERMISSIONS="
_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

_PROJECT_TARGETS = (
    "chromium-swarm",
    "gerritcodereview-ci",
)

_SERVICE_ACCOUNT_TARGETS = (
    (
        "chromium-swarm",
        "bots-gerrit@chromium-swarm.iam.gserviceaccount.com",
    ),
    (
        "gerritcodereview-ci",
        "gerrit-luci-try-builder@"
        "gerritcodereview-ci.iam.gserviceaccount.com",
    ),
)

_PROJECT_PERMISSIONS = (
    "resourcemanager.projects.get",
    "resourcemanager.projects.getIamPolicy",
    "resourcemanager.projects.setIamPolicy",
    "resourcemanager.projects.update",
    "resourcemanager.projects.delete",
    "serviceusage.services.use",
    "iam.serviceAccounts.list",
    "iam.serviceAccounts.create",
    "compute.projects.get",
    "compute.projects.setCommonInstanceMetadata",
    "compute.instances.list",
    "compute.instances.get",
    "compute.instances.getSerialPortOutput",
    "compute.instances.create",
    "compute.instances.delete",
    "compute.instances.start",
    "compute.instances.stop",
    "compute.instances.reset",
    "compute.instances.setMetadata",
    "compute.instances.setServiceAccount",
    "compute.instances.osLogin",
    "compute.instances.osAdminLogin",
    "cloudbuild.builds.get",
    "cloudbuild.builds.list",
    "cloudbuild.builds.create",
    "logging.logEntries.list",
    "logging.logEntries.create",
    "storage.buckets.list",
    "storage.buckets.create",
)

_SERVICE_ACCOUNT_PERMISSIONS = (
    "iam.serviceAccounts.get",
    "iam.serviceAccounts.getIamPolicy",
    "iam.serviceAccounts.setIamPolicy",
    "iam.serviceAccounts.actAs",
    "iam.serviceAccounts.getAccessToken",
    "iam.serviceAccounts.getOpenIdToken",
    "iam.serviceAccounts.implicitDelegation",
    "iam.serviceAccounts.signBlob",
    "iam.serviceAccounts.signJwt",
    "iam.serviceAccountKeys.create",
    "iam.serviceAccountKeys.get",
    "iam.serviceAccountKeys.list",
    "iam.serviceAccountKeys.delete",
)


def _post_json(url, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        url,
        data=json.dumps(body, separators=(",", ":")).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.getcode(), json.load(response)


def _local_auth_token(local_auth):
    url = (
        "http://127.0.0.1:{}/rpc/" "LuciLocalAuthService.GetOAuthToken"
    ).format(local_auth["rpc_port"])
    return _post_json(
        url,
        {
            "account_id": "system",
            "scopes": [_CLOUD_PLATFORM_SCOPE],
            "secret": local_auth["secret"],
        },
    )


def _test_permissions(url, permissions, token):
    try:
        status, reply = _post_json(
            url,
            {"permissions": list(permissions)},
            token=token,
        )
    except urllib.error.HTTPError as error:
        return {
            "granted": [],
            "http_status": error.code,
            "requested_count": len(permissions),
        }
    except (OSError, ValueError) as error:
        return {
            "error": type(error).__name__,
            "granted": [],
            "requested_count": len(permissions),
        }
    return {
        "granted": sorted(set(reply.get("permissions", []))),
        "http_status": status,
        "requested_count": len(permissions),
    }


def _collect():
    context_path = os.environ.get("LUCI_CONTEXT")
    if not context_path:
        return {"local_auth_present": False}

    with open(context_path, encoding="utf-8") as context_file:
        context = json.load(context_file)
    local_auth = context.get("local_auth") or {}
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
        "local_auth_present": bool(local_auth),
        "projects": {},
        "service_accounts": {},
        "system_oauth": {"issued": False},
    }
    if not any(account["id"] == "system" for account in accounts):
        result["system_oauth"]["reason"] = "not_listed"
        return result

    try:
        status, reply = _local_auth_token(local_auth)
    except urllib.error.HTTPError as error:
        result["system_oauth"]["http_status"] = error.code
        return result
    except (OSError, ValueError) as error:
        result["system_oauth"]["error"] = type(error).__name__
        return result

    token = reply.pop("access_token", "")
    result["system_oauth"] = {
        "error_code": reply.get("error_code", 0),
        "expiry": reply.get("expiry"),
        "http_status": status,
        "issued": bool(token) and not reply.get("error_code"),
        "requested_scopes": [_CLOUD_PLATFORM_SCOPE],
    }
    if not token:
        return result

    try:
        for project in _PROJECT_TARGETS:
            url = (
                "https://cloudresourcemanager.googleapis.com/v1/projects/"
                + urllib.parse.quote(project, safe="")
                + ":testIamPermissions"
            )
            result["projects"][project] = _test_permissions(
                url,
                _PROJECT_PERMISSIONS,
                token,
            )

        for project, email in _SERVICE_ACCOUNT_TARGETS:
            resource = "projects/{}/serviceAccounts/{}".format(
                urllib.parse.quote(project, safe=""),
                urllib.parse.quote(email, safe=""),
            )
            url = (
                "https://iam.googleapis.com/v1/{}:testIamPermissions"
            ).format(resource)
            result["service_accounts"][email] = _test_permissions(
                url,
                _SERVICE_ACCOUNT_PERMISSIONS,
                token,
            )
    finally:
        del token
    return result


def test_vrp_luci_system_permissions():
    evidence = json.dumps(_collect(), separators=(",", ":"), sort_keys=True)
    warnings.warn(_MARKER + evidence, stacklevel=1)
