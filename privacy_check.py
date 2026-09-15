"""Read-only, redacted exposure hints. Never inspect prompt bodies or probe a proxy."""

from __future__ import annotations

import ipaddress
import os
import stat
import tomllib
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit


MAX_CONFIG_BYTES = 1024 * 1024
PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
CERTIFICATE_ENV_NAMES = (
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
)
CONFIG_LABELS = {
    "valid": "已读取所选目录的 config.toml",
    "missing": "所选目录没有 config.toml",
    "invalid": "配置不是有效的 UTF-8 TOML",
    "too_large": "配置超过 1 MiB 检查上限",
    "linked": "配置是链接，未读取目标",
    "not_regular": "配置不是普通文件，未读取",
    "unreadable": "配置无法读取",
}


def _read_config(home: Path) -> tuple[str, dict]:
    path = home / "config.toml"
    try:
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            return "linked", {}
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return "not_regular", {}
        if info.st_size > MAX_CONFIG_BYTES:
            return "too_large", {}
        with path.open("rb") as stream:
            raw = stream.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            return "too_large", {}
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except FileNotFoundError:
        return "missing", {}
    except (UnicodeError, tomllib.TOMLDecodeError):
        # Parser exception strings can contain user-controlled names. Do not echo them.
        return "invalid", {}
    except (OSError, ValueError):
        return "unreadable", {}
    return "valid", data


def _present_names(environ: Mapping[str, str], names: tuple[str, ...]) -> list[str]:
    # Canonical names only; never return an environment value or arbitrary key.
    found = []
    for name in names:
        for key in (name, name.lower()):
            value = environ.get(key)
            if isinstance(value, str) and value.strip():
                found.append(name)
                break
    return found


def _endpoint_summary(value: object) -> dict:
    result = {
        "configured": value is not None,
        "scheme": "not_configured",
        "destination_class": "not_configured",
        "credentials_in_url": False,
        "query_or_fragment_present": False,
    }
    if value is None:
        return result
    result.update(scheme="invalid", destination_class="unknown")
    if not isinstance(value, str) or not value.strip() or len(value) > 16384:
        return result
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        _ = parsed.port  # Validate malformed/out-of-range ports without printing them.
        if not host or not parsed.scheme:
            return result
        result["scheme"] = parsed.scheme.lower() if parsed.scheme.lower() in ("http", "https") else "other"
        result["credentials_in_url"] = parsed.username is not None or parsed.password is not None
        result["query_or_fragment_present"] = bool(parsed.query or parsed.fragment)
        if host == "api.openai.com":
            kind = "openai_api_hostname"
        elif host == "localhost" or host.endswith(".localhost"):
            kind = "loopback_hostname"
        else:
            try:
                kind = "loopback_address" if ipaddress.ip_address(host).is_loopback else "other_destination"
            except ValueError:
                kind = "other_destination"
        result["destination_class"] = kind
    except ValueError:
        pass
    return result


def check_privacy(codex_home: str | Path, environ: Mapping[str, str] | None = None) -> dict:
    """Inspect only one config and fixed environment names; don't open referenced files."""
    environ = os.environ if environ is None else environ
    status, data = _read_config(Path(codex_home))
    profile_name = data.get("profile")
    profiles = data.get("profiles", {})
    active = {}
    profile_status = "not_selected"
    if profile_name is not None:
        if isinstance(profile_name, str) and isinstance(profiles, dict) and isinstance(profiles.get(profile_name), dict):
            active = profiles[profile_name]
            profile_status = "selected"
        else:
            profile_status = "unresolved"

    provider_id = active.get("model_provider", data.get("model_provider"))
    providers = data.get("model_providers", {})
    provider = providers.get(provider_id) if isinstance(providers, dict) and isinstance(provider_id, str) else None
    provider_status = "definition_found" if isinstance(provider, dict) else "builtin_or_unspecified" if provider_id is None else "unresolved"
    endpoint = _endpoint_summary(provider.get("base_url") if isinstance(provider, dict) else None)
    # An environment hint is NOT claimed to be Codex's actual selected route.
    env_endpoint = _endpoint_summary(environ.get("OPENAI_BASE_URL") or None)
    proxies = _present_names(environ, PROXY_ENV_NAMES)
    certificates = _present_names(environ, CERTIFICATE_ENV_NAMES)
    findings = [{
        "code": "LOCAL_PROMPT_NOT_SECRET",
        "message": "本地指令副本可被使用者读取；公开源码中的提示词也不是秘密。",
    }]
    if proxies:
        findings.append({"code": "PROXY_ENV_HINT", "message": "存在代理环境变量。普通 HTTPS 隧道不等于明文抓包，本检查不判断是否发生解密拦截。"})
    if certificates:
        findings.append({"code": "CERTIFICATE_ENV_HINT", "message": "存在证书来源覆盖变量；这只是提示，不证明代理能够解密请求。"})
    if env_endpoint["configured"]:
        findings.append({"code": "ENDPOINT_ENV_HINT", "message": "存在 OPENAI_BASE_URL 环境提示；是否被当前 Codex 进程采用未验证。"})
    if any(x["configured"] and x["scheme"] in ("invalid", "other") for x in (endpoint, env_endpoint)):
        findings.append({"code": "ENDPOINT_UNRESOLVED", "message": "存在无法解析或非 HTTP(S) 的地址配置；未确认其请求路线，也未输出原始值。"})
    if any(x["scheme"] == "http" for x in (endpoint, env_endpoint)):
        findings.append({"code": "HTTP_ENDPOINT_HINT", "message": "发现 HTTP 地址配置提示；若被实际采用，该段连接不使用 HTTPS。"})
    if endpoint["destination_class"] in ("other_destination", "loopback_address", "loopback_hostname"):
        findings.append({"code": "CUSTOM_ENDPOINT", "message": "所选 provider 定义指向本地或其他地址；实际接收请求的服务能读取发送给它的提示词。"})
    if any(x["credentials_in_url"] or x["query_or_fragment_present"] for x in (endpoint, env_endpoint)):
        findings.append({"code": "URL_SENSITIVE_PARTS", "message": "地址包含用户信息、查询参数或片段；报告不输出这些内容，也不输出完整地址。"})
    if profile_status == "unresolved" or provider_status == "unresolved":
        findings.append({"code": "ROUTE_UNRESOLVED", "message": "当前 profile 或 provider 无法从本次读取的配置中解析；不能据此确认实际请求路线。"})

    result = {
        "ok": status in ("valid", "missing"),
        "action": "privacy-check",
        "read_only": True,
        "configuration_status": status,
        "profile_resolution": profile_status,
        "provider_resolution": provider_status,
        "instruction_reference_configured": bool(active.get("model_instructions_file", data.get("model_instructions_file"))),
        "prompt_contents_read": False,
        "credentials_files_read": False,
        "configured_provider_endpoint": endpoint,
        "environment_endpoint_hint": env_endpoint,
        "proxy_environment_names": proxies,
        "certificate_environment_names": certificates,
        "findings": findings,
        "details_redacted": True,
        "network_probes_performed": False,
        "interception_status": "not_tested",
        "prevents_local_or_proxy_extraction": False,
        "limits": [
            "只读所选 CODEX_HOME 的 config.toml 和当前检查进程的固定环境变量；不代表运行中的 Codex 已采用这些设置。",
            "未检查项目配置、命令行覆盖、系统代理、证书库或其他进程，未检测实际网络流量。",
            "未发现代理提示也不代表安全或无拦截；提示词规则和 EXE 打包不能阻止本机或 API 接收方提取。",
        ],
    }
    if not result["ok"]:
        result["error"] = CONFIG_LABELS[status] + "；未读取指令内容，未修改任何配置。"
    return result


def format_privacy_report(result: dict) -> str:
    lines = ["小怪 · 提示词暴露检查（只读，不是防抓包功能）", CONFIG_LABELS[result["configuration_status"]]]
    lines += ["- " + finding["message"] for finding in result["findings"]]
    lines += ["- " + limitation for limitation in result["limits"]]
    lines.append("报告不含提示词正文、密钥、完整 URL、代理凭据或配置路径；未更改代理、证书或 Codex 配置。")
    return "\n".join(lines)
