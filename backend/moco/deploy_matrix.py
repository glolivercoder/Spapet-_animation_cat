"""
backend/moco/deploy_matrix.py
Matriz de Decisão Paramétrica para Servidor e Deploy (Padrão MOCO).
Geração automatizada de Infraestrutura como Código (IaC) e commits no Gitea.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class DeployDecision(BaseModel):
    recommended_target: str  # 'cloudflare_pages', 'coolify_docker', 'supabase_fullstack'
    target_display_name: str
    rationale: str
    iac_manifests: Dict[str, str]  # filename -> content
    suggested_branch: str = "infra/deploy-setup"
    commit_message: str


class DeployDecisionMatrix:
    @staticmethod
    def evaluate(
        app_name: str = "my-concio-app",
        has_websockets: bool = True,
        uses_sqlite: bool = True,
        is_pure_static: bool = False,
        requires_supabase_rls: bool = False,
        backend_port: int = 8000,
    ) -> DeployDecision:
        """
        Avalia os requisitos do MVP e gera a infraestrutura de deploy determinística recomendada.
        """
        if is_pure_static and not has_websockets and not uses_sqlite:
            target = "cloudflare_pages"
            name = "Cloudflare Pages / Vercel (Jamstack Puro)"
            rationale = "Aplicação 100% estática sem WebSockets ou SQLite local; CDN global com latência zero e custo zero."
            manifests = {
                "wrangler.toml": DeployDecisionMatrix.generate_wrangler_toml(app_name),
            }
            msg = f"chore(infra): add wrangler.toml configuration for Cloudflare Pages ({app_name})"

        elif requires_supabase_rls and not uses_sqlite:
            target = "supabase_fullstack"
            name = "Supabase MCP + Frontend Edge"
            rationale = "Requisitos fortes de banco relacional multi-tenant com Row Level Security (RLS) e Auth nativo."
            manifests = {
                "supabase/config.toml": f'project_id = "{app_name}"\n[api]\nport = 54321\n',
                "docker-compose.yml": DeployDecisionMatrix.generate_docker_compose(app_name, backend_port),
            }
            msg = f"feat(infra): configure Supabase RLS migrations and edge bridge for {app_name}"

        else:
            # Padrão Devmaster: FastAPI + WebSockets + SQLite local
            target = "coolify_docker"
            name = "Coolify / Docker Container Gerenciado"
            rationale = (
                "Backend Python/FastAPI com WebSockets em tempo real e banco SQLite integrado. "
                "Coolify provê deploy contínuo em VPS com persistência de volumes e SSL automático sem Docker Desktop."
            )
            manifests = {
                "Dockerfile": DeployDecisionMatrix.generate_dockerfile("fastapi"),
                "docker-compose.yml": DeployDecisionMatrix.generate_docker_compose(app_name, backend_port),
            }
            msg = f"feat(infra): add production Dockerfile and compose for Coolify containerization ({app_name})"

        return DeployDecision(
            recommended_target=target,
            target_display_name=name,
            rationale=rationale,
            iac_manifests=manifests,
            suggested_branch="infra/deploy-setup",
            commit_message=msg,
        )

    @staticmethod
    def generate_dockerfile(stack_type: str = "fastapi") -> str:
        return (
            "# Dockerfile gerado automaticamente pela Matriz de Deploy MOCO\n"
            "FROM python:3.11-slim\n\n"
            "WORKDIR /app\n\n"
            "ENV PYTHONDONTWRITEBYTECODE=1 \\\n"
            "    PYTHONUNBUFFERED=1 \\\n"
            "    PIP_NO_CACHE_DIR=1\n\n"
            "# Dependências do sistema para compilação nativa\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
            "    curl git build-essential sqlite3 \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n\n"
            "COPY requirements.txt .\n"
            "RUN pip install --upgrade pip && pip install -r requirements.txt\n\n"
            "COPY . .\n\n"
            "# Volume persistente para o banco SQLite do histórico e dados\n"
            "VOLUME [\"/app/workspace\", \"/app/data\"]\n\n"
            "EXPOSE 8000\n\n"
            "CMD [\"uvicorn\", \"app:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n"
        )

    @staticmethod
    def generate_docker_compose(app_name: str, port: int = 8000) -> str:
        return (
            f"version: '3.8'\n\n"
            f"services:\n"
            f"  {app_name}:\n"
            f"    build: .\n"
            f"    container_name: {app_name}_prod\n"
            f"    restart: unless-stopped\n"
            f"    ports:\n"
            f"      - \"{port}:8000\"\n"
            f"    volumes:\n"
            f"      - {app_name}_data:/app/workspace\n"
            f"      - {app_name}_db:/app/data\n"
            f"    environment:\n"
            f"      - ENVIRONMENT=production\n"
            f"      - PORT=8000\n\n"
            f"volumes:\n"
            f"  {app_name}_data:\n"
            f"  {app_name}_db:\n"
        )

    @staticmethod
    def generate_wrangler_toml(app_name: str, dist_dir: str = "dist") -> str:
        return (
            f'name = "{app_name}"\n'
            f'compatibility_date = "2026-11-01"\n'
            f'pages_build_output_dir = "{dist_dir}"\n'
        )

