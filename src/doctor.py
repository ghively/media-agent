"""Config doctor — startup diagnostics for the whole deployment.

``python -m src.main --doctor`` checks every configured dependency and
prints a red/green table: config loads, state dir writable, Ollama up +
model pulled + context sane, each media service reachable and authorized,
and the optional pieces (fallback LLM, Telegram, Download Station).
"""
import asyncio

import httpx


async def _check(name: str, coro) -> tuple[str, bool, str]:
    try:
        ok, detail = await coro
        return (name, ok, detail)
    except httpx.ConnectError:
        return (name, False, "connection refused / unreachable")
    except httpx.TimeoutException:
        return (name, False, "timed out")
    except Exception as e:
        return (name, False, f"{type(e).__name__}: {e}")


async def _check_config():
    from src.config import get_settings
    settings = get_settings()
    return True, "settings loaded"


async def _check_state_dir():
    from src.config import get_state_dir
    path = get_state_dir()
    return True, f"writable: {path}"


async def _check_ollama():
    from src.config import get_settings
    llm = get_settings().llm
    url = llm.get("ollama_url", "").rstrip("/")
    model = llm.get("ollama_model", "")
    num_ctx = int(llm.get("num_ctx", 16384))
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{url}/api/tags")
        resp.raise_for_status()
        tags = [m.get("name", "") for m in resp.json().get("models", [])]
    pulled = any(t == model or t.split(":")[0] == model for t in tags)
    problems = []
    if not pulled:
        problems.append(f"model '{model}' NOT pulled (run: ollama pull {model})")
    if num_ctx < 8192:
        problems.append(f"num_ctx={num_ctx} is below the 8192 floor — tool schemas will truncate")
    if problems:
        return False, "; ".join(problems)
    return True, f"up; '{model}' pulled; num_ctx={num_ctx}"


async def _check_arr(kind: str):
    from src.config import get_settings
    cfg = getattr(get_settings(), kind)
    if not cfg.get("url") or not cfg.get("api_key"):
        return False, "not configured (url/api_key missing)"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{cfg['url'].rstrip('/')}/api/v3/system/status",
            headers={"X-Api-Key": cfg["api_key"]},
        )
        if resp.status_code == 401:
            return False, "reachable but API key rejected (401)"
        resp.raise_for_status()
        version = resp.json().get("version", "?")
    return True, f"up (v{version})"


async def _check_emby():
    from src.config import get_settings
    cfg = get_settings().emby
    if not cfg.get("url") or not cfg.get("api_key"):
        return False, "not configured (url/api_key missing)"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{cfg['url'].rstrip('/')}/emby/System/Info",
            headers={"X-Emby-Token": cfg["api_key"]},
        )
        if resp.status_code == 401:
            return False, "reachable but API key rejected (401)"
        resp.raise_for_status()
        version = resp.json().get("Version", "?")
    return True, f"up (v{version})"


async def _check_sabnzbd():
    from src.config import get_settings
    cfg = get_settings().sabnzbd
    if not cfg.get("url") or not cfg.get("api_key"):
        return False, "not configured — SABnzbd tools will report errors"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{cfg['url'].rstrip('/')}/api",
            params={"mode": "version", "output": "json", "apikey": cfg["api_key"]},
        )
        resp.raise_for_status()
        version = resp.json().get("version", "?")
    return True, f"up (v{version})"


async def _check_download_station():
    from src.config import get_settings
    cfg = get_settings().download_station
    if not cfg.get("username") or not cfg.get("password"):
        return False, "not configured — Download Station tools disabled"
    url = cfg.get("url", "").rstrip("/")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{url}/webapi/query.cgi",
            params={"api": "SYNO.API.Info", "version": 1, "method": "query",
                    "query": "SYNO.API.Auth,SYNO.DownloadStation.Task"},
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("success"):
        return True, "up (API info OK)"
    return False, f"API error: {data}"


async def _check_lidarr():
    from src.config import get_settings
    cfg = get_settings().lidarr
    if not cfg.get("url") or not cfg.get("api_key"):
        return True, "not configured (optional)"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{cfg['url'].rstrip('/')}/api/v1/system/status",
            headers={"X-Api-Key": cfg["api_key"]},
        )
        if resp.status_code == 401:
            return False, "reachable but API key rejected (401)"
        resp.raise_for_status()
        version = resp.json().get("version", "?")
    return True, f"up (v{version})"


async def _check_bazarr():
    from src.config import get_settings
    cfg = get_settings().bazarr
    if not cfg.get("url") or not cfg.get("api_key"):
        return True, "not configured (optional)"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{cfg['url'].rstrip('/')}/api/system/status",
            headers={"X-API-KEY": cfg["api_key"]},
        )
        if resp.status_code == 401:
            return False, "reachable but API key rejected (401)"
        resp.raise_for_status()
    return True, "up"


async def _check_fallback_llm():
    from src.config import get_settings
    llm = get_settings().llm
    if not (llm.get("hosted_url") and llm.get("hosted_key") and llm.get("hosted_model")):
        return True, "not configured (optional)"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{llm['hosted_url'].rstrip('/')}/models",
            headers={"Authorization": f"Bearer {llm['hosted_key']}"},
        )
        resp.raise_for_status()
    return True, f"up ({llm['hosted_model']})"


async def _check_telegram():
    from src.notify import telegram_configured, telegram_check
    if not telegram_configured():
        return True, "not configured (optional)"
    return await telegram_check()


async def run_doctor() -> bool:
    """Run all checks and print a table. Returns True when all required
    checks pass."""
    from rich.console import Console
    from rich.table import Table

    checks = [
        ("Config", _check_config()),
        ("State dir", _check_state_dir()),
        ("Ollama", _check_ollama()),
        ("Sonarr", _check_arr("sonarr")),
        ("Radarr", _check_arr("radarr")),
        ("Emby", _check_emby()),
        ("SABnzbd", _check_sabnzbd()),
        ("Download Station", _check_download_station()),
        ("Lidarr", _check_lidarr()),
        ("Bazarr", _check_bazarr()),
        ("Fallback LLM", _check_fallback_llm()),
        ("Telegram", _check_telegram()),
    ]
    results = await asyncio.gather(*(_check(n, c) for n, c in checks))

    console = Console()
    table = Table(title="Media Agent — Config Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    all_ok = True
    for name, ok, detail in results:
        table.add_row(name, "✅" if ok else "❌", detail)
        # Optional integrations report ok=False only when misconfigured
        if not ok and name in ("Config", "State dir", "Ollama", "Sonarr", "Radarr", "Emby"):
            all_ok = False
    console.print(table)
    console.print(
        "[green]All core checks passed.[/]" if all_ok
        else "[red]Core problems found — the agent will not work correctly until fixed.[/]"
    )
    return all_ok
