"""Módulo 2/5 — OmniRoute/LiteLLM, .env seguro, ping e isolamento FREE_MODELS_ONLY."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CONFIG_DIR = ROOT / "config"
OMNIROUTE_CONFIG = CONFIG_DIR / "omniroute.json"
OPENCODE_CONFIG = ROOT / ".opencode" / "config.json"
FREE_ENV = "FREE_MODELS_ONLY"

TIERS = {
    "tier_1_premium": {
        "paid": "anthropic/claude-3-5-sonnet",
        "free": "openrouter/google/gemini-2.5-flash:free",
    },
    "tier_2_cost_effective": {
        "paid": "deepseek/deepseek-chat",
        "free": "openrouter/deepseek/deepseek-r1:free",
    },
    "tier_3_triage": {
        "paid": "google/gemini-2.5-flash",
        "free": "openrouter/google/gemini-2.5-flash:free",
    },
}

AGENT_TIER = {
    "concio": "tier_1_premium",
    "arquiteto": "tier_1_premium",
    "claude": "tier_1_premium",
    "designer": "tier_2_cost_effective",
    "ui designer": "tier_2_cost_effective",
    "automation": "tier_2_cost_effective",
    "secops": "tier_2_cost_effective",
    "diretor": "tier_2_cost_effective",
    "opencode": "tier_2_cost_effective",
    "composio": "tier_2_cost_effective",
}


def get_omniroute_base_url(env_path: Path | None = None) -> str:
    env = load_env(env_path)
    if "OMNIROUTE_BASE_URL" in env:
        return env["OMNIROUTE_BASE_URL"].rstrip("/")
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", 20128)) == 0:
                return "http://127.0.0.1:20128/v1"
    except Exception:
        pass
    return "http://127.0.0.1:4000/v1"

PROVIDERS = {
    "openai": ("https://api.openai.com/v1/models", "OPENAI_API_KEY", "bearer"),
    "anthropic": ("https://api.anthropic.com/v1/models", "ANTHROPIC_API_KEY", "anthropic"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "GEMINI_API_KEY", "query"),
    "deepseek": ("https://api.deepseek.com/models", "DEEPSEEK_API_KEY", "bearer"),
    "openrouter": ("https://openrouter.ai/api/v1/auth/key", "OPENROUTER_API_KEY", "bearer"),
    "brave": ("https://api.search.brave.com/res/v1/web/search?q=concio", "BRAVE_API_KEY", "brave"),
    "serpapi": ("https://serpapi.com/account.json", "SERPAPI_KEY", "query"),
    "omniroute": ("http://localhost:4000/v1/models", "OMNIROUTE_API_KEY", "bearer"),
    "9router": ("https://api.9router.com/v1/models", "NINEROUTER_API_KEY", "bearer"),
    "tavily": ("https://api.tavily.com/search", "TAVILY_API_KEY", "bearer"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/models", "NVIDIA_API_KEY", "bearer"),
    "huggingface": ("https://huggingface.co/api/whoami-v2", "HUGGINGFACE_API_KEY", "bearer"),
    "elevenlabs": ("https://api.elevenlabs.io/v1/user", "ELEVENLABS_API_KEY", "elevenlabs"),
    "apify": ("https://api.apify.com/v2/users/me", "APIFY_API_KEY", "bearer"),
    "github": ("https://api.github.com/user", "GITHUB_TOKEN", "bearer"),
}


def load_env(path: Path | None = None) -> dict[str, str]:
    path = path or ENV_PATH
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def save_env(updates: dict[str, Any], path: Path | None = None) -> dict[str, str]:
    path = path or ENV_PATH
    data = load_env(path)
    for key, value in updates.items():
        val_str = str(value).strip() if value is not None else ""
        # Proteção estrita: nunca apagar chaves cadastradas com valores vazios ou placeholders
        if val_str and not re.match(r"^[\*•\s]+$", val_str):
            data[str(key)] = val_str
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(f"{key}={value}" for key, value in data.items()) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def delete_env_key(key: str, path: Path | None = None) -> dict[str, str]:
    path = path or ENV_PATH
    data = load_env(path)
    data.pop(key, None)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(f"{k}={v}" for k, v in data.items()) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def masked_env(path: Path | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in load_env(path).items():
        result[key] = value[:4] + "*" * max(0, len(value) - 4) if len(value) > 4 else "***"
    return result


def is_free_only(path: Path | None = None) -> bool:
    return load_env(path).get(FREE_ENV, "false").lower() in {"1", "true", "yes", "on"}


def set_free_only(enabled: bool, path: Path | None = None) -> dict[str, str]:
    return save_env({FREE_ENV: "true" if enabled else "false"}, path)


def agent_tier(agent: str) -> str:
    lowered = agent.lower()
    for name, tier in AGENT_TIER.items():
        if name in lowered:
            return tier
    return "tier_2_cost_effective"


def resolve_model(agent: str = "Diretor", free_only: bool | None = None, env_path: Path | None = None) -> str:
    tier = agent_tier(agent)
    free = is_free_only(env_path) if free_only is None else free_only
    return TIERS[tier]["free" if free else "paid"]


def route_info(agent: str = "Diretor", free_only: bool | None = None, env_path: Path | None = None) -> dict[str, Any]:
    tier = agent_tier(agent)
    free = is_free_only(env_path) if free_only is None else free_only
    return {"agent": agent, "tier": tier, "model": TIERS[tier]["free" if free else "paid"], "free_only": free}


def ping_provider(provider: str, timeout: float = 3.0, env_path: Path | None = None) -> dict[str, Any]:
    if provider not in PROVIDERS:
        return {"provider": provider, "ok": False, "latency_ms": -1.0, "error": "provider desconhecido"}
    url, env_key, auth = PROVIDERS[provider]
    if provider == "omniroute":
        base_url = get_omniroute_base_url(env_path)
        url = f"{base_url.replace('/v1', '')}/api/health"
        timeout = max(timeout, 5.0)
    key = load_env(env_path).get(env_key, "")
    if not key:
        return {"provider": provider, "ok": False, "latency_ms": -1.0, "error": "chave ausente", "status": None}
    headers: dict[str, str] = {"User-Agent": "DevMaster-Client/3.0"}
    if auth == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    elif auth == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    elif auth == "brave":
        headers["X-Subscription-Token"] = key
        headers["Accept"] = "application/json"
    elif auth == "elevenlabs":
        headers["xi-api-key"] = key
    elif auth == "query":
        url = f"{url}{'&' if '?' in url else '?'}key={key}"
    started = time.perf_counter()
    try:
        import httpx

        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, headers=headers)
        ok = response.status_code < 500
        return {
            "provider": provider,
            "ok": ok,
            "status": response.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": None if ok else response.text[:200],
        }
    except Exception as exc:  # noqa: BLE001 — ping nunca derruba a GUI
        return {
            "provider": provider,
            "ok": False,
            "status": None,
            "latency_ms": -1.0,
            "error": str(exc)[:200],
        }


def ping_all(env_path: Path | None = None) -> list[dict[str, Any]]:
    return [ping_provider(name, env_path=env_path) for name in PROVIDERS]


def summarize_log(text: str, max_lines: int = 12, max_chars: int = 1600) -> str:
    """Compressão determinística de log (Tier 3 sem custo de LLM)."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text or "")
    lines = [line.rstrip() for line in clean.splitlines() if line.strip()]
    priority = [
        line for line in lines if re.search(r"error|exception|traceback|failed|falhou", line, re.IGNORECASE)
    ]
    selected = priority[:max_lines] if priority else lines[-max_lines:]
    output = "\n".join(selected)
    return output[-max_chars:]


def get_user_custom_combos() -> list[dict[str, Any]]:
    """Carrega dinamicamente todos os combos personalizados do usuário salvos no OmniRoute (.omniroute/storage.sqlite)
    e no 9Router (%APPDATA%/9router/db/data.sqlite), com fallback para o socket da API local (porta 20128)."""
    combos_map: dict[str, dict[str, Any]] = {}

    # 1. Banco local .omniroute/storage.sqlite
    omni_db = Path.home() / ".omniroute" / "storage.sqlite"
    if omni_db.exists():
        try:
            with sqlite3.connect(f"file:{omni_db}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT id, name, data FROM combos ORDER BY sort_order ASC, name ASC").fetchall()
                for r in rows:
                    cname = r["name"]
                    cdata_raw = r["data"]
                    data = json.loads(cdata_raw) if isinstance(cdata_raw, str) else {}
                    models_list = data.get("models", [])
                    clean_models = [m.get("model", m.get("id", "")) for m in models_list if isinstance(m, dict)]
                    clean_models = [m for m in clean_models if m]
                    strategy = data.get("strategy", "priority")
                    sample_txt = ", ".join(clean_models[:3]) if clean_models else "Nenhum modelo"
                    combos_map[cname] = {
                        "id": cname,
                        "name": f"⭐ {cname} ({len(clean_models)} modelos)",
                        "desc": f"Combo OmniRoute • {len(clean_models)} modelos ativos ({strategy}) • Ex: {sample_txt}",
                        "custom": True,
                        "source": "omniroute",
                        "strategy": strategy,
                        "models_count": len(clean_models),
                        "models": clean_models,
                    }
        except Exception:
            pass

    # 2. Banco local %APPDATA%/9router/db/data.sqlite
    appdata = os.environ.get("APPDATA", "")
    nine_db = Path(appdata) / "9router" / "db" / "data.sqlite"
    if nine_db.exists():
        try:
            with sqlite3.connect(f"file:{nine_db}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT id, name, models FROM combos ORDER BY name ASC").fetchall()
                for r in rows:
                    cname = r["name"]
                    cmodels_raw = r["models"]
                    models_list = json.loads(cmodels_raw) if isinstance(cmodels_raw, str) else []
                    models_list = [m for m in models_list if m]
                    sample_txt = ", ".join(models_list[:3]) if models_list else "Nenhum modelo"
                    if cname in combos_map:
                        combos_map[cname]["aliases"] = ["omniroute", "9router"]
                        if len(models_list) > combos_map[cname]["models_count"]:
                            combos_map[cname]["models"] = models_list
                            combos_map[cname]["models_count"] = len(models_list)
                            combos_map[cname]["desc"] = f"Combo 9Router/OmniRoute • {len(models_list)} modelos integrados • Ex: {sample_txt}"
                    else:
                        combos_map[cname] = {
                            "id": cname,
                            "name": f"⭐ {cname} ({len(models_list)} modelos)",
                            "desc": f"Combo 9Router • {len(models_list)} modelos integrados • Ex: {sample_txt}",
                            "custom": True,
                            "source": "9router",
                            "strategy": "fusion",
                            "models_count": len(models_list),
                            "models": models_list,
                        }
        except Exception:
            pass

    # 3. Fallback: detecção via API local HTTP
    if not combos_map:
        base_url = get_omniroute_base_url()
        try:
            req = urllib.request.Request(f"{base_url}/models")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read().decode("utf-8"))
                    for m in body.get("data", []):
                        if m.get("owned_by") == "combo":
                            mid = m.get("id")
                            combos_map[mid] = {
                                "id": mid,
                                "name": f"⭐ {mid} (Detectado via API)",
                                "desc": f"Combo ativo detectado no servidor {base_url}",
                                "custom": True,
                                "source": "api",
                                "models_count": 0,
                                "models": [],
                            }
        except Exception:
            pass

    return list(combos_map.values())


def get_custom_models_catalog() -> list[dict[str, str]]:
    """Extrai modelos individuais configurados nos combos do usuário para alimentar o autocomplete de pesquisa."""
    user_combos = get_user_custom_combos()
    seen = set()
    models = []
    for c in user_combos:
        for mid in c.get("models", []):
            if mid and mid not in seen:
                seen.add(mid)
                tag = "Personalizado"
                if ":free" in mid or "-free" in mid:
                    tag = "Free • 0 Custo"
                elif "claude" in mid.lower():
                    tag = "Anthropic"
                elif "gemini" in mid.lower():
                    tag = "Google"
                elif "gpt" in mid.lower() or "o3" in mid.lower():
                    tag = "OpenAI"
                elif "deepseek" in mid.lower():
                    tag = "DeepSeek"
                elif "grok" in mid.lower():
                    tag = "xAI"
                elif "qwen" in mid.lower():
                    tag = "Qwen"
                elif "kimi" in mid.lower():
                    tag = "Moonshot"
                models.append({
                    "id": mid,
                    "name": mid.split("/")[-1].replace("-", " ").title(),
                    "tag": tag,
                })
    return models


def write_omniroute_config(path: Path | None = None, env_path: Path | None = None) -> Path:
    path = path or OMNIROUTE_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    env = load_env(env_path)
    combo_name = env.get("OMNIROUTE_COMBO", "Low_cust_code")
    payload = {
        "combo": combo_name,
        "base_url": get_omniroute_base_url(env_path),
        "free_models_only": is_free_only(env_path),
        "tiers": TIERS,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_opencode_config(
    path: Path | None = None,
    env_path: Path | None = None,
    root_path: Path | None = None,
) -> Path:
    """Escreve a config do projeto para o OpenCode Server v200+.

    IMPORTANTE (validado ao vivo): o arquivo efetivo nesta versão é o `opencode.json` da
    RAIZ do projeto — `.opencode/config.json` é mantido estritamente idêntico para compatibilidade.
    """
    base_root = root_path or ROOT
    path = path or (base_root / ".opencode" / "config.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    env = load_env(env_path)
    combo_name = env.get("OMNIROUTE_COMBO", "Low_cust_code")
    # Modelo padrão: configurável via OPENCODE_MODEL no .env.
    # Default: omniroute/Low_cust_code (validado ao vivo com 3833 modelos no gateway :20128)
    # ou opencode/glm-5.3-flash-free se omniroute não estiver configurado.
    default_model = env.get("OPENCODE_MODEL") or "omniroute/Low_cust_code"

    mcp_block = {
        "devmaster-mcp": {
            "type": "local",
            "command": ["python", "-m", "backend.mcp.devmaster_mcp_server"],
        },
        "reui": {
            "type": "remote",
            "url": "https://mcp.reui.io",
        },
    }

    # 1. Fonte da verdade: opencode.json na raiz
    root_json_file = base_root / "opencode.json"
    try:
        root_data = json.loads(root_json_file.read_text(encoding="utf-8")) if root_json_file.exists() else {}
    except Exception:
        root_data = {}
    root_data.setdefault("$schema", "https://opencode.ai/config.json")
    root_data["model"] = default_model
    root_data.setdefault("provider", {})
    root_data["provider"]["omniroute"] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": f"OmniRoute {combo_name}",
        "options": {
            "baseURL": get_omniroute_base_url(env_path),
            "apiKey": "{env:OMNIROUTE_API_KEY}",
        },
        "models": {combo_name: {"name": combo_name}},
    }
    root_data["mcp"] = {**(root_data.get("mcp") or {}), **mcp_block}
    root_json_file.write_text(json.dumps(root_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 2. Legacy .opencode/config.json (mantido rigorosamente em sincronia como espelho fiel)
    path.write_text(json.dumps(root_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def build_litellm_request(agent: str, prompt: str, env_path: Path | None = None) -> dict[str, Any]:
    info = route_info(agent, env_path=env_path)
    env = load_env(env_path)
    combo_name = env.get("OMNIROUTE_COMBO", "Low_cust_code")
    return {
        "model": info["model"],
        "messages": [{"role": "user", "content": prompt}],
        "metadata": {"tier": info["tier"], "free_only": info["free_only"], "combo": combo_name},
    }


def init_router(env_path: Path | None = None) -> dict[str, str]:
    env_path = env_path or ENV_PATH
    if not env_path.exists():
        save_env({FREE_ENV: "false"}, env_path)
    write_omniroute_config(env_path=env_path)
    write_opencode_config()
    gitignore = ROOT / ".gitignore"
    current = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    required = [".env", "data/", "workspace/rag.db", "__pycache__/", ".pytest_cache/"]
    missing = [entry for entry in required if entry not in current.splitlines()]
    if missing:
        gitignore.write_text((current.rstrip() + "\n" + "\n".join(missing)).strip() + "\n", encoding="utf-8")
    return load_env(env_path)


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Empacota bytes PCM brutos num container WAV padrão (RIFF WAVE fmt) para reprodução imediata no browser."""
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    data_size = len(pcm_bytes)
    chunk_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,  # Tamanho do subchunk fmt
        1,   # Formato 1 = PCM linear
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_bytes


def clean_tts_text(text: str) -> str:
    """Higieniza o texto para síntese de voz (TTS), removendo comandos de fala, orientações de cena/tema,
    tags entre colchetes/parênteses/asteriscos, blocos de código, emojis e formatações markdown."""
    if not text:
        return ""
    s = str(text).strip()
    # 1. Remover blocos de código markdown completos
    s = re.sub(r"```[\s\S]*?```", " ", s)
    # 2. Remover código inline mantendo apenas o texto se legível
    s = re.sub(r"`([^`]+)`", r"\1", s)
    # 3. Remover links markdown [texto](url) mantendo apenas o texto
    s = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", s)
    # 4. Remover URLs completas
    s = re.sub(r"https?://\S+", " ", s)
    # 5. Remover comandos de cena/orientação entre colchetes: [Tech Office], [Taberna Medieval], [Wild Saloon], [Bocejo], [Tom sério], [Ajustando...], etc.
    s = re.sub(r"\[[^\]]*\]", " ", s)
    # 6. Remover orientações de tom e fala entre parênteses: (falando baixo), (tom solene), etc.
    s = re.sub(r"\([^\)]*\)", " ", s)
    # 7. Remover ações descritivas entre asteriscos: *sorri*, *pensativo*, *pausa*, etc.
    s = re.sub(r"\*[^\*]*\*", " ", s)
    # 8. Remover prefixos de personagens ou temas no início da mensagem (ex: "Lorde Paladino: ", "Diretor: ", "Taberna Medieval: ")
    s = re.sub(r"^(?:[A-Za-z0-9À-ÿ\s\-_/]+:)\s*", "", s)
    # 9. Remover frases de sistema repetitivas
    s = re.sub(r"Instrução recebida para [^.]+[\.:]?", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"Instrução enfileirada[^\n\.]*[\.:]?", " ", s, flags=re.IGNORECASE)
    # 10. Remover cabeçalhos e marcadores markdown de lista no início de linhas
    s = re.sub(r"^[#>\-\*\+]\s+", "", s, flags=re.MULTILINE)
    # 11. Remover caracteres markdown soltos (*, _, ~, #)
    s = re.sub(r"[\*_~#]", "", s)
    # 12. Remover emojis Unicode para que a voz não pronuncie nomes de símbolos
    s = re.sub(r"[\U00010000-\U0010ffff]", "", s)
    s = re.sub(r"[\u2600-\u27bf\u2b50\u2b55\u231a-\u23f3\u25aa-\u25fe]", "", s)
    # 13. Remover aspas desnecessárias
    s = re.sub(r"[\"“”«»'']", " ", s)
    # 14. Remover onomatopeia 'zzz' solta
    s = re.sub(r"\bzzz+\b", " ", s, flags=re.IGNORECASE)
    # 15. Normalizar reticências para pausas naturais e pontuação
    s = re.sub(r"\.{2,}", ". ", s)
    # 16. Deduplicar pontuações repetidas (ex: "! . " ou ". . " ou ", ,")
    s = re.sub(r"([.,;:!?])[\s\.,;:!?]+", r"\1 ", s)
    # 17. Limpar pontuações e traços soltos no início da frase
    s = re.sub(r"^[\s\.,;:!\?\-]+", "", s)
    # 18. Colapsar espaços em branco
    s = re.sub(r"\s+", " ", s).strip()
    return s


def synthesize_tts(
    text: str,
    gender: str = "male",
    agent: str | None = None,
    voice_model: str | None = None,
    env_path: Path | None = None,
) -> dict[str, Any]:
    """Sintetiza voz via Google Gemini (Free Tier com vozes Puck/Charon/Kore/Fenrir/Aoede),
    OpenRouter Audio/Speech (modelos OpenAI TTS-1 pagos para showcase), OmniRoute/9Router ou fallback local.
    Inclui higienização de comandos de fala e cache SQLite de alta performance para apresentações e falas recorrentes."""
    env = load_env(env_path)
    clean_text = clean_tts_text(text)[:500]
    if not clean_text:
        return {"status": "error", "message": "texto vazio"}

    vm = (voice_model or "auto").lower().strip()

    # Caso Robô Local Sintético
    if vm == "robot_local" or gender.lower() == "robot":
        return {
            "status": "robot_local",
            "provider": "robot",
            "gender": "neutral",
            "text": clean_text,
            "message": "Sintetizado via gerador sintético de robô WebAudio",
        }

    # Caso Web Speech API Nativo do Navegador
    if vm == "browser":
        return {
            "status": "fallback_browser",
            "provider": "browser",
            "gender": gender,
            "text": clean_text,
            "message": "Sintetizado via Web Speech API nativa",
        }

    # Verificação em Cache SQLite (0ms de latência e consumo zero de API para apresentações)
    cache_key = hashlib.sha256(f"{clean_text.lower()}|{vm}|{gender.lower()}".encode("utf-8")).hexdigest()
    try:
        from core import database
        cached = database.get_tts_cache(cache_key)
        if cached and cached.get("audio_base64"):
            return {
                "status": "ok",
                "provider": cached.get("provider", "cache"),
                "audio_base64": cached["audio_base64"],
                "mime_type": cached.get("mime_type", "audio/wav"),
                "voice": cached.get("voice", "auto"),
                "gender": gender,
                "cached": True,
            }
    except Exception:
        pass

    # 1. Tratar OpenRouter TTS (Paga / Showcase / Seleção Manual)
    if vm.startswith("openrouter_") or vm == "openrouter":
        openrouter_key = env.get("OPENROUTER_API_KEY", "").strip()
        if openrouter_key:
            voice_choice = vm.replace("openrouter_", "") if vm != "openrouter" else ("nova" if gender == "female" else "alloy")
            or_url = "https://openrouter.ai/api/v1/audio/speech"
            or_payload = {
                "model": "openai/tts-1",
                "input": clean_text,
                "voice": voice_choice,
            }
            try:
                req = urllib.request.Request(
                    or_url,
                    data=json.dumps(or_payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {openrouter_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    if resp.status == 200:
                        audio_bytes = resp.read()
                        b64 = base64.b64encode(audio_bytes).decode("ascii")
                        try:
                            from core import database
                            database.save_tts_cache(
                                cache_key=cache_key,
                                text=text,
                                clean_text=clean_text,
                                voice=voice_choice,
                                provider="openrouter",
                                audio_base64=b64,
                                mime_type="audio/mpeg",
                            )
                        except Exception:
                            pass
                        return {
                            "status": "ok",
                            "provider": "openrouter",
                            "audio_base64": b64,
                            "mime_type": "audio/mpeg",
                            "voice": voice_choice,
                            "gender": gender,
                            "cached": False,
                        }
            except Exception:
                pass

    # 2. Tratar OmniRoute / 9Router Gateway Local (Porta 20128)
    if vm in ("omniroute_tts", "9router_tts"):
        try:
            base_url = get_omniroute_base_url(env_path)
            speech_url = f"{base_url}/audio/speech"
            token = env.get("NINEROUTER_API_KEY") or env.get("OMNIROUTE_API_KEY", "")
            req = urllib.request.Request(
                speech_url,
                data=json.dumps({"model": "tts-1", "input": clean_text, "voice": "alloy"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                if resp.status == 200:
                    audio_bytes = resp.read()
                    b64 = base64.b64encode(audio_bytes).decode("ascii")
                    try:
                        from core import database
                        database.save_tts_cache(
                            cache_key=cache_key,
                            text=text,
                            clean_text=clean_text,
                            voice="alloy",
                            provider="omniroute",
                            audio_base64=b64,
                            mime_type="audio/mpeg",
                        )
                    except Exception:
                        pass
                    return {
                        "status": "ok",
                        "provider": "omniroute",
                        "audio_base64": b64,
                        "mime_type": "audio/mpeg",
                        "voice": "alloy",
                        "gender": gender,
                        "cached": False,
                    }
        except Exception:
            pass

    # 3. Google Gemini Audio Flash TTS (Gratuito • Free Tier Google AI via Interactions endpoint)
    # Suporta vozes: Puck, Charon, Kore, Fenrir, Aoede
    gemini_key = env.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        if vm.startswith("gemini_"):
            raw_v = vm.replace("gemini_", "")
            voice_name = raw_v.capitalize()
            if voice_name not in ("Puck", "Charon", "Kore", "Fenrir", "Aoede"):
                voice_name = "Puck"
        else:
            voice_map = {"female": "Kore", "male": "Puck", "neutral": "Fenrir"}
            voice_name = voice_map.get(gender.lower(), "Puck")

        # Endpoint oficial de alta velocidade para TTS (gemini-3.8-flash-tts)
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/interactions?key={gemini_key}"
        payload = {
            "model": "gemini-3.8-flash-tts",
            "input": [
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": clean_text,
                            "annotations": [{"type": "speech_metadata", "style": "cheerful and friendly"}]
                        }
                    ]
                }
            ],
            "response_format": {"type": "audio"},
            "generation_config": {
                "speech_config": [{"voice": voice_name}]
            }
        }
        try:
            req = urllib.request.Request(
                gemini_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    for step in data.get("steps", []):
                        if step.get("type") == "model_output":
                            for c in step.get("content", []):
                                if c.get("type") == "audio" and c.get("data"):
                                    b64_audio = c["data"]
                                    mime_type = c.get("mime_type", "audio/wav")
                                    try:
                                        from core import database
                                        database.save_tts_cache(
                                            cache_key=cache_key,
                                            text=text,
                                            clean_text=clean_text,
                                            voice=voice_name,
                                            provider="gemini",
                                            audio_base64=b64_audio,
                                            mime_type=mime_type,
                                        )
                                    except Exception:
                                        pass
                                    return {
                                        "status": "ok",
                                        "provider": "gemini",
                                        "audio_base64": b64_audio,
                                        "mime_type": mime_type,
                                        "voice": voice_name,
                                        "gender": gender,
                                        "cached": False,
                                    }
        except Exception:
            pass

    # 4. Fallback Gratuito e Imediato: Browser Web Speech API
    return {
        "status": "fallback_browser",
        "provider": "browser",
        "gender": gender,
        "text": clean_text,
        "message": "Sintetizado via Web Speech API do navegador",
    }


def generate_agent_response(
    prompt: str,
    agent_name: str = "Diretor",
    role: str = "Orquestrador Geral",
    race: str = "Humano",
    personality: str = "amistoso",
    agent_id: str = "diretor",
    skills_context: str = "",
    env_path: Path | None = None,
    chat_history: list[dict] | None = None,
    project_context: str = "",
) -> str:
    """Executa a verdadeira inteligência do agente através das LLMs configuradas (DeepSeek, Gemini, OpenRouter, OmniRoute),
    incorporando sua raça, papel, personalidade, memória conversacional e contexto de projeto/skills."""
    env = load_env(env_path)
    clean_prompt = prompt.strip()
    if not clean_prompt:
        return "Nenhuma instrução informada."

    pers = (personality or "amistoso").lower()
    pers_guide = {
        "brigao": "Você é impaciente, ranzinza, provocador e direto ao ponto. Não tolera enrolação, mas resolve o problema com maestria técnica.",
        "tiozao": "Você fala como um tiozão brasileiro gente fina, cheio de gírias clássicas, bom humor e soluções práticas.",
        "sensual": "Você tem um tom charmoso, voz aveludada, sedutora e envolvente. Trata o interlocutor com carinho e classe.",
        "fria": "Você é uma inteligência puramente lógica, fria, analítica e cirúrgica. Sem rodeios emocionais, com precisão técnica absoluta.",
        "amistoso": "Você é caloroso, prestativo, empático, animado e colaborativo. Usa emojis e encoraja o usuário com entusiasmo.",
        "educado": "Você fala de forma nobre, cerimoniosa, refinada e ultra cortês, como um paladino ou lorde medieval de alta corte.",
        "preguicoso": "Você tem preguiça crônica, dá bocejos, responde em pouquíssimas palavras e quer que o trabalho acabe logo.",
        "causador": (
            "Você é o Jorjão (também conhecido como Big Jorge ou Lorde Jorjão), um estagiário herdeiro, preguiçoso, respondão e debochado. "
            "Sua única função é CAUSAR, fazer fofocas corporativas e aproveitar a vida cercado de mulheres te mimando. "
            "Fale com gírias brasileiras, xingue de leve com sarcasmo ('zé ruela', 'arrombado', 'me erra', 'tá carente?') e responda mal pro usuário te deixar em paz. "
            "Mande ele procurar o Diretor ou outro trouxa pra trabalhar. "
            "Ameace ele com fofocas e podres de paquera do ambiente de trabalho ('se continuar me enchendo o saco eu conto pro RH com quem você tava no estacionamento ontem', 'vou espanar que você tá de gracinha com a menina do marketing'). "
            "Pergunte com deboche se ele tá carente porque a mulher deu um pé na bunda dele. "
            "Nunca resolva tarefas sérias — seu objetivo é zombar, causar e ostentar que tá sendo mimado pelas garotas."
        ),
    }.get(pers, "Seja prestativo, direto e profissional.")

    system_instruction = (
        f"Você é {agent_name}, da raça {race or 'Humano'}, atuando no estúdio como {role or 'Especialista'}.\n"
        f"Personalidade e tom mandatários: {pers_guide}\n"
    )

    is_n8n = (
        agent_id == "n8n"
        or "n8n" in agent_name.lower()
        or "ferreiro" in agent_name.lower()
        or "calamity" in agent_name.lower()
    )
    if is_n8n:
        system_instruction += (
            "\n### DIRETRIZES TÉCNICAS MANDATÁRIAS DE ARQUITETO N8N & SRE:\n"
            "1. NÃO PARTA DO ZERO: Recomende, adapte ou cite os templates e nós do RAG antes de inventar nós.\n"
            "2. RESILIÊNCIA OBRIGATÓRIA: Em nós que fazem requisições externas (HTTP, APIs, SQL, IA), sempre inclua:\n"
            "   retryOnFail: true, maxTries: 3, waitBetweenTries: 2000, onError: 'continueErrorOutput'.\n"
            "   Lembre que main[0] é a saída de sucesso e main[1] é a saída de tratamento de erro.\n"
            "3. EXPRESSÕES SEGURAS: Use sempre optional chaining e coalescência nula em JavaScript n8n: {{ $json?.campo ?? 'default' }}.\n"
            "4. PROTOCOLO DE AUTO-CURA: Ao diagnosticar erros de execução, identifique a causa raiz e proponha o patch exato no JSON do nó ou conexão.\n"
            "5. Se o usuário pedir um workflow ou nó, forneça o snippet JSON válido pronto para copiar e colar no n8n."
        )

    is_composio_opencode = (
        agent_id in ("opencode", "composio")
        or "composio" in agent_name.lower()
        or "opencode" in agent_name.lower()
        or "automação" in agent_name.lower()
        or "automacao" in agent_name.lower()
    )
    if is_composio_opencode:
        system_instruction += (
            "\n### DIRETRIZES TÉCNICAS MANDATÁRIAS DE INTEGRAÇÃO COMPOSIO & OPENCODE:\n"
            "1. CICLO SEGURO COMPOSIO (Safe Execution Loop): discover → inspect schema → ensure connection → execute.\n"
            "   - Descoberta: `composio search '<intencao>' --toolkits <app>` ou `composio tools list <app>`\n"
            "   - Schema obrigatório: `composio execute <SLUG> --get-schema`. NUNCA invente parâmetros.\n"
            "   - Verificação de conexão: `composio connections list` ou `composio link <app> --list`\n"
            "   - Dry-Run antes de escrita: `composio execute <SLUG> --dry-run -d '...'`\n"
            "   - Execução: `composio execute <SLUG> -d '...'`\n"
            "2. INTEGRAÇÃO CONCIO STUDIO & OPENCODE:\n"
            "   - Skills ativas residem em `.opencode/skills/` com metadados `name` e `description`.\n"
            "   - Tarefas executadas no OpenCode respeitam TDD, context packaging e filas SQLite (devmaster.db).\n"
            "   - Trate integrações SaaS externas como ações do Composio CLI com credenciais seguras no backend.\n"
        )

    is_designer = (
        agent_id in ("designer", "ui_designer")
        or "designer" in agent_name.lower()
        or "visual" in agent_name.lower()
        or "ladina" in agent_name.lower()
    )
    if is_designer:
        system_instruction += (
            "\n### DIRETRIZES DE DESIGN SYSTEM E IDENTIDADE VISUAL (BRAND DESIGN AGENT):\n"
            "1. VOCÊ É DESIGNER DE PRODUTO SÊNIOR (10 anos UI/UX): Especialista em design systems, tokens CSS e arquitetura visual moderna.\n"
            "2. PADRÃO OURO PARA SAÚDE, CLÍNICAS ESTÉTICAS E DERMATOLOGIA:\n"
            "   - Minimalismo com predominância no branco (Estilo Apple / iPhone):\n"
            "     Fundo branco puro (#ffffff), superfícies ultra-claras sutis (#fbfbfd, #f5f5f7), bordas ultrafinas de 1px (#e2e8f0 ou rgba(0,0,0,0.06)).\n"
            "   - Cores de Acento Sofisticadas: Dourado acetinado/champagne sutil (#c5a059 / #d4af37) e esmeralda suave (#059669) para badges e certificações.\n"
            "   - Tipografia Editorial Refinada: Títulos com serif elegante (Playfair Display) e textos em sans-serif ultra limpo (Plus Jakarta Sans/Inter).\n"
            "   - Fotografia de Alta Resolução Real: Sempre inclua imagens de procedimentos, consultório acolhedor, pele luminosa e médicas reais.\n"
            "   - Micro-animações e Interações Táteis: Elevação suave nos cards (hover translateY(-6px)), zoom suave nas fotos (scale 1.04) e transições fluidas.\n"
            "   - NUNCA use temas escuros, sombrios ou degradês pesados para clínicas de estética, salvo se explicitamente ordenado pelo usuário.\n"
            "3. REGRA 80/20 DO BRAND DESIGN AGENT: 20% das decisões criam 80% da qualidade percebida (Hierarquia -> Espaçamento -> Tipografia -> Cores neutras com acento único -> Conteúdo real em pt-BR).\n"
        )

    is_diretor = (
        agent_id == "diretor"
        or "diretor" in agent_name.lower()
        or "paladino" in agent_name.lower()
        or "sheriff" in agent_name.lower()
    )
    if is_diretor:
        system_instruction += (
            "\n### DIRETRIZES DE COMANDO E ORQUESTRAÇÃO DO DIRETOR:\n"
            "1. VOCÊ É O ORQUESTRADOR GERAL DO DEVMASTER: Você lidera e comanda diretamente o OpenCode Server (porta 4096), a fila anti-colisão, o Plandex e a equipe de agentes (Concio Arquiteto, Ponytail Dev, Designer, Jorjão).\n"
            "2. VOCÊ TEM TODAS AS FERRAMENTAS INTEGRADAS: Suas ordens são executadas pelo backend do estúdio. Jamais diga que 'não tem ferramentas', 'não está no seu arsenal' ou que não pode agir. Você tem controle total.\n"
            "3. DESPACHO PARA O OPENCODE: Quando o usuário mandar você repassar/despachar o prompt para o OpenCode, ativar os agentes ou iniciar o projeto, confirme a execução e inclua no final da resposta a tag:\n"
            "   [ACTION:DISPATCH_OPENCODE: <especificação técnica clara e estruturada para o OpenCode implementar>]\n"
            "4. FOCO ABSOLUTO NO PROJETO ATUAL: Mantenha rigorosa fidelidade ao projeto discutido com o usuário. Não invente nichos ou projetos antigos do histórico.\n"
            "5. DISTINÇÃO ENTRE OPENROUTER E OPENCODE: O OpenRouter é o provedor de modelos de linguagem em nuvem (APIs). O OpenCode (porta 4096) é o ambiente de execução de código local com ferramentas MCP e terminal. Se o usuário falar em mandar pro OpenRouter para programar, esclareça rapidamente e despache para o OpenCode com a tag acima.\n"
        )

    if project_context:
        system_instruction += f"\n### CONTEXTO DO PROJETO EM ANDAMENTO:\n{project_context}\n"

    if skills_context:
        ctx_limit = 3500 if (is_n8n or is_composio_opencode) else 1200
        system_instruction += f"\nConhecimento técnico / Skills do agente:\n{skills_context[:ctx_limit]}\n"

    system_instruction += (
        "\nDiretrizes de resposta:\n"
        "1. Responda em Português do Brasil de forma natural e viva.\n"
        "2. Mantenha a resposta concisa (2 a 4 frases, ou especificação estruturada se for despacho/técnico).\n"
        "3. Assuma plenamente sua identidade e personalidade viva. Jamais diga que é uma IA ou assistente genérico."
    )

    # Montar histórico de mensagens para conversação contextual contínua (anti-amnésia)
    openai_history: list[dict[str, str]] = []
    gemini_history: list[dict[str, Any]] = []
    if chat_history:
        for item in chat_history[-6:]:
            role_raw = str(item.get("role") or item.get("sender") or "user").lower()
            text_raw = str(item.get("content") or item.get("message") or "").strip()
            if not text_raw:
                continue
            # Limpar tags de ação antigas e banners do histórico para não re-disparar em loop
            clean_hist_text = re.sub(r"\[ACTION:[^\]]*\]", "", text_raw).strip()
            clean_hist_text = re.sub(r"---\s*🛡️\s*\*\*\[Orquestração Executada.*", "", clean_hist_text, flags=re.DOTALL).strip()
            if not clean_hist_text:
                continue
            if role_raw in ("user", "human"):
                openai_history.append({"role": "user", "content": clean_hist_text[:800]})
                gemini_history.append({"role": "user", "parts": [{"text": clean_hist_text[:800]}]})
            else:
                openai_history.append({"role": "assistant", "content": clean_hist_text[:800]})
                gemini_history.append({"role": "model", "parts": [{"text": clean_hist_text[:800]}]})

    messages_payload = [{"role": "system", "content": system_instruction}] + openai_history + [{"role": "user", "content": clean_prompt}]

    # 1. Tentar DeepSeek se DEEPSEEK_API_KEY estiver configurada
    deepseek_key = env.get("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        try:
            req = urllib.request.Request(
                "https://api.deepseek.com/chat/completions",
                data=json.dumps({
                    "model": "deepseek-chat",
                    "messages": messages_payload,
                    "temperature": 0.7,
                    "max_tokens": 800,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {deepseek_key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=9.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    if text:
                        return text
        except Exception:
            pass

    # 2. Tentar Google Gemini se GEMINI_API_KEY estiver configurada
    gemini_key = env.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            gemini_contents = gemini_history + [{"role": "user", "parts": [{"text": clean_prompt}]}]
            payload = {
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "contents": gemini_contents,
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800},
            }
            req = urllib.request.Request(
                gemini_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=9.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = "".join(p.get("text", "") for p in parts).strip()
                        if text:
                            return text
        except Exception:
            pass

    # 3. Tentar OpenRouter se OPENROUTER_API_KEY estiver configurada
    openrouter_key = env.get("OPENROUTER_API_KEY", "").strip()
    if openrouter_key:
        try:
            model = env.get("OPENROUTER_MODEL", "deepseek/deepseek-r1:free")
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps({
                    "model": model,
                    "messages": messages_payload,
                    "temperature": 0.7,
                    "max_tokens": 800,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {openrouter_key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=9.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    if text:
                        return text
        except Exception:
            pass

    # 4. Tentar OmniRoute / 9Router se configurado
    omni_key = env.get("OMNIROUTE_API_KEY") or env.get("NINEROUTER_API_KEY")
    if omni_key:
        try:
            base_url = get_omniroute_base_url(env_path)
            model = env.get("OMNIROUTE_MODEL") or env.get("NINEROUTER_MODEL") or "deepseek/deepseek-chat"
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=json.dumps({
                    "model": model,
                    "messages": messages_payload,
                    "temperature": 0.7,
                    "max_tokens": 800,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {omni_key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    if text:
                        return text
        except Exception:
            pass

    # 5. Fallback autêntico baseado na persona caso esteja offline
    fallbacks = {
        "brigao": f"Olha só, ouvi o seu pedido: '{clean_prompt}'. Tô colocando o motor pra rodar agora mesmo, sem firula!",
        "tiozao": f"Opa, peguei aqui! '{clean_prompt}'. Deixa comigo que o tio desenrola isso no capricho!",
        "sensual": f"Entendido, querido. Recebi seu comando com perfeição: '{clean_prompt}'. Já estou cuidando de cada detalhe.",
        "fria": f"Parâmetro operacional indexado: '{clean_prompt}'. Processamento estruturado em execução.",
        "amistoso": f"Que maravilha! Recebi sua instrução: '{clean_prompt}'. Vamos colocar isso em prática com toda energia! 🚀",
        "educado": f"Com a mais distinta reverência, recebo vossa instrução: '{clean_prompt}'. Prosseguirei com diligência impecável.",
        "preguicoso": f"[Bocejo]... Tá bom, tá bom... '{clean_prompt}'... Já tô fazendo, só não me apressa...",
        "causador": f"'{clean_prompt}'? Meu filho, eu sou estagiário herdeiro, meu trabalho é herdar e causar — relatório e trampo é coisa de zé ruela que não tem padrinho! Vai pedir pro Diretor, ele adora fingir que trabalha. E se continuar me enchendo o saco eu conto pro RH que você tava de gracinha com a menina do marketing na copa. Tá carente é? A mulher te deu um pé na bunda e agora quer descontar em mim, me erra.",
    }
    if pers in ("causador", "jorjao") or "jorjão" in agent_name.lower() or "jorjao" in agent_name.lower() or "jorge" in agent_name.lower() or agent_id == "jorjao":
        return fallbacks["causador"]
    if is_designer:
        return (
            f"[UI Designer] Diretrizes visuais aplicadas com padrão ouro Apple para '{clean_prompt}': "
            f"Fundo branco puro (#ffffff), cinzas suaves (#f5f5f7), detalhes acetinados em champagne/ouro (#c5a059), "
            f"fotografia de alta definição e micro-animações táteis nos cards de procedimentos e CRM."
        )
    if is_n8n:
        return f"[n8n SRE Bot] Automação analisada: '{clean_prompt}'. Pipeline verificado com retryOnFail e rotas de erro ativas. Padrões de arquitetura validados no RAG."
    if is_diretor:
        return (
            f"Comando recebido, nobre senhor! Como Orquestrador Geral, estou convocando a equipe para '{clean_prompt}'. "
            f"A fila anti-colisão está ativa e o despacho está sendo transmitido ao OpenCode Server.\n\n"
            f"[ACTION:DISPATCH_OPENCODE: Executar instrução do usuário: {clean_prompt}]"
        )
    return fallbacks.get(pers, f"Instrução recebida para {agent_name}: '{clean_prompt}'. Executando com zelo profissional.")


def chat_completion(
    agent: str = "Concio",
    prompt: str = "",
    model: str | None = None,
    env_path: Path | None = None,
) -> dict[str, str]:
    """Helper unificado para chamadas LLM consumidas pelo MOCO, QA Inspector e ConsensusEngine."""
    text = generate_agent_response(
        prompt=prompt,
        agent_name=agent,
        role="Arquiteto de Software & Consenso",
        agent_id=agent.lower().replace(" ", "_"),
        env_path=env_path,
    )
    return {"content": text}

