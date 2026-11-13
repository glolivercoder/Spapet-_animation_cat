"""Módulo de Catálogo de Projetos (Pydantic v2).

Carrega e valida config/project_catalog.yml, resolve perfis com herança,
dials de design, verticais de negócio (Odoo Pareto 20%) e grava workspace/docs/project.json.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "config" / "project_catalog.yml"
DEFAULT_DOCS = ROOT / "workspace" / "docs"


class Dials(BaseModel):
    variance: int = Field(default=5, ge=1, le=10)
    density: int = Field(default=5, ge=1, le=10)
    motion: int = Field(default=3, ge=1, le=10)


class ProfileDef(BaseModel):
    preset: Optional[str] = None
    extends: Optional[str] = None
    requires_vertical: bool = False
    uses_vertical: bool = False
    domain_ref: Optional[str] = None
    start_from: list[str] = Field(default_factory=list)
    dials: Optional[Dials] = None
    add_skills: list[str] = Field(default_factory=list)
    mcp_on_workflow_turn: Optional[str] = None
    concio_decide: bool = False


class VerticalDef(BaseModel):
    odoo_ref: list[str] = Field(default_factory=list)
    extends: Optional[str] = None
    particularidades: list[str] = Field(default_factory=list)
    particularidades_add: list[str] = Field(default_factory=list)
    compliance: Optional[str] = None


class CatalogConfig(BaseModel):
    version: int = 2
    presets: dict[str, str] = Field(default_factory=dict)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    profiles: dict[str, ProfileDef] = Field(default_factory=dict)
    verticals: dict[str, VerticalDef] = Field(default_factory=dict)
    compliance: dict[str, str] = Field(default_factory=dict)


class ProjectProfileRequest(BaseModel):
    profile_id: str
    vertical_id: Optional[str] = None
    custom_overrides: Optional[dict[str, Any]] = None


def load_catalog(path: Path | str = CATALOG_PATH) -> CatalogConfig:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo de catálogo não encontrado: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return CatalogConfig.model_validate(raw)


def resolve_vertical(vertical_id: str, catalog: CatalogConfig) -> dict[str, Any]:
    if vertical_id not in catalog.verticals:
        raise ValueError(
            f"Vertical '{vertical_id}' não encontrada no catálogo. Verticais válidas: {list(catalog.verticals.keys())}"
        )
    v_def = catalog.verticals[vertical_id]
    
    odoo_refs = list(v_def.odoo_ref)
    particularidades = list(v_def.particularidades)
    compliance_key = v_def.compliance

    if v_def.extends and v_def.extends in catalog.verticals:
        parent_v = catalog.verticals[v_def.extends]
        for r in parent_v.odoo_ref:
            if r not in odoo_refs:
                odoo_refs.append(r)
        for part in parent_v.particularidades:
            if part not in particularidades:
                particularidades.append(part)
        if not compliance_key:
            compliance_key = parent_v.compliance

    for part_add in v_def.particularidades_add:
        if part_add not in particularidades:
            particularidades.append(part_add)

    compliance_text = catalog.compliance.get(compliance_key or "", "")

    return {
        "id": vertical_id,
        "odoo_ref": odoo_refs,
        "particularidades": particularidades,
        "compliance_key": compliance_key,
        "compliance_notes": compliance_text,
    }


def resolve_project_profile(
    profile_id: str,
    vertical_id: Optional[str] = None,
    catalog: Optional[CatalogConfig] = None,
    custom_overrides: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cat = catalog or load_catalog()
    if profile_id not in cat.profiles:
        raise ValueError(
            f"Perfil '{profile_id}' não encontrado no catálogo. Perfis válidos: {list(cat.profiles.keys())}"
        )

    p_def = cat.profiles[profile_id]

    # Resolver herança de perfil
    parent_def = None
    if p_def.extends and p_def.extends in cat.profiles:
        parent_def = cat.profiles[p_def.extends]

    preset = p_def.preset or (parent_def.preset if parent_def else "astro")
    domain_ref = p_def.domain_ref or (parent_def.domain_ref if parent_def else None)
    requires_vertical = p_def.requires_vertical or (parent_def.requires_vertical if parent_def else False)
    uses_vertical = p_def.uses_vertical or (parent_def.uses_vertical if parent_def else False) or requires_vertical

    start_from = list(p_def.start_from)
    if parent_def:
        for sf in parent_def.start_from:
            if sf not in start_from:
                start_from.append(sf)

    dials_model = p_def.dials or (parent_def.dials if parent_def else None) or Dials(variance=5, density=5, motion=3)
    dials_dict = dials_model.model_dump()

    # Validação de vertical
    if requires_vertical and not vertical_id:
        raise ValueError(f"O perfil '{profile_id}' exige a seleção de uma vertical de negócio.")

    vertical_data = None
    if vertical_id:
        vertical_data = resolve_vertical(vertical_id, cat)

    # Resolução de skills ativas
    active_skills: list[str] = []
    # Base skills
    for skill_name in cat.skills.get("design", ["brand-design-agent"]):
        if skill_name not in active_skills:
            active_skills.append(skill_name)

    if parent_def:
        for sk in parent_def.add_skills:
            if sk not in active_skills:
                active_skills.append(sk)
    for sk in p_def.add_skills:
        if sk not in active_skills:
            active_skills.append(sk)

    mcp_workflow = p_def.mcp_on_workflow_turn or (parent_def.mcp_on_workflow_turn if parent_def else None)

    resolved: dict[str, Any] = {
        "profile_id": profile_id,
        "vertical_id": vertical_id,
        "preset": preset,
        "preset_description": cat.presets.get(str(preset), ""),
        "start_from": start_from,
        "dials": dials_dict,
        "domain_ref": domain_ref,
        "requires_vertical": requires_vertical,
        "uses_vertical": uses_vertical,
        "active_skills": active_skills,
        "audit_f4_skills": cat.skills.get("audit_f4", ["web-design-guidelines"]),
        "mcp_on_workflow_turn": mcp_workflow,
        "concio_decide": p_def.concio_decide,
        "vertical": vertical_data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if custom_overrides:
        resolved.update(custom_overrides)

    return resolved


def save_project_profile(profile_data: dict[str, Any], docs_dir: Path | str = DEFAULT_DOCS) -> Path:
    p = Path(docs_dir)
    p.mkdir(parents=True, exist_ok=True)
    out_file = p / "project.json"
    out_file.write_text(json.dumps(profile_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_file


def get_current_project_profile(docs_dir: Path | str = DEFAULT_DOCS) -> dict[str, Any] | None:
    out_file = Path(docs_dir) / "project.json"
    if not out_file.is_file():
        return None
    try:
        return json.loads(out_file.read_text(encoding="utf-8"))
    except Exception:
        return None


PROJECTS_FILE = ROOT / "data" / "projects.json"

DEFAULT_PROJECTS = [
    {
        "id": "proj-nina-hermosa-crm",
        "name": "Clínica Nina Hermosa CRM & Agendamento",
        "prompt": "🚀 PROJETO: Clínica de Estética Avançada Nina Hermosa (CRM & Agendamento Médico)\n\n📋 BRIEFING EXECUTIVO & POSICIONAMENTO:\n- Marca: Clínica de Estética Avançada Nina Hermosa\n- Vertical: CRM Médico Especializado & Estética Avançada (Dermatologia, Harmonização, Laser)\n- Stack: Vite + React 19 + TypeScript (Strict) + Tailwind v4 + shadcn/ui + Supabase RLS 100% ativo\n- Conformidade: LGPD Art. 11 (Dados sensíveis de saúde, auditoria de leitura/escrita)\n- Telas P0: Kanban da Jornada, Ficha Unificada da Paciente, Gestão de Procedimentos e Modal de Agendamento Rápido.",
        "profile_id": "crm_vertical",
        "vertical_id": "medico",
        "agents": ["diretor", "ponytail", "designer", "concio", "n8n"],
        "mcps": ["context7", "playwright", "figma"],
        "search_apis": ["tavily", "google_search"],
        "automations": ["n8n", "composio"],
        "status": "active",
        "created_at": "2026-11-08T10:00:00Z",
        "updated_at": "2026-11-08T14:00:00Z",
    }
]


def list_projects() -> list[dict[str, Any]]:
    """Retorna a lista de projetos salvos ou inicializa com os padrões."""
    if not PROJECTS_FILE.is_file():
        save_projects_list(DEFAULT_PROJECTS)
        return list(DEFAULT_PROJECTS)
    try:
        data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data
        save_projects_list(DEFAULT_PROJECTS)
        return list(DEFAULT_PROJECTS)
    except Exception:
        return list(DEFAULT_PROJECTS)


def save_projects_list(projects: list[dict[str, Any]]) -> None:
    """Salva a lista completa de projetos em data/projects.json."""
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")


def get_project(project_id: str) -> dict[str, Any] | None:
    """Recupera um projeto pelo ID."""
    for p in list_projects():
        if p.get("id") == project_id:
            return p
    return None


def create_or_update_project(project_data: dict[str, Any]) -> dict[str, Any]:
    """Cria ou atualiza um projeto com ID único, agente Gitea incorporado e timestamps."""
    projects = list_projects()
    p_id = project_data.get("id")
    now_iso = datetime.now(timezone.utc).isoformat()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", project_data.get("name", "projeto").lower()).strip("-") or "projeto"
    if not p_id:
        p_id = f"proj-{slug}-{int(datetime.now(timezone.utc).timestamp())}"
        project_data["id"] = p_id
        project_data["created_at"] = now_iso
    project_data["updated_at"] = now_iso

    # Garante que o agente DevOps GiteaDog está incorporado na lista de agentes do projeto
    raw_agents = project_data.get("agents")
    if raw_agents is None:
        agents = ["diretor", "ponytail", "designer", "concio", "giteadog"]
    elif isinstance(raw_agents, list):
        agents = list(raw_agents)
    else:
        agents = [str(raw_agents)]
    if "giteadog" not in agents:
        agents.append("giteadog")
    project_data["agents"] = agents

    # Pasta local do projeto (isolada para versionamento e monitoramento nativo)
    folder = project_data.get("folder_path")
    if not folder:
        folder = str((ROOT / "workspace" / "projects" / slug).resolve())
        project_data["folder_path"] = folder

    # Inicializa repositório Git, exclusões em .git/info/exclude e monitoramento GiteaDog
    try:
        from backend.moco.gitea_manager import gitea_manager
        gitea_info = gitea_manager.init_project_repo(
            project_id=p_id,
            project_name=project_data.get("name", "Projeto"),
            folder_path=folder
        )
        project_data["gitea"] = gitea_info
    except Exception as g_err:
        project_data["gitea"] = {
            "status": "monitoring",
            "folder_path": folder,
            "agent": "giteadog",
            "error": str(g_err)
        }

    if project_data.get("status") == "active":
        for p in projects:
            if p.get("id") != p_id:
                p["status"] = "inactive"

    found = False
    for i, p in enumerate(projects):
        if p.get("id") == p_id:
            projects[i] = {**p, **project_data}
            found = True
            break
    if not found:
        projects.insert(0, project_data)

    save_projects_list(projects)
    return project_data


def delete_project(project_id: str) -> bool:
    """Remove um projeto pelo ID."""
    projects = list_projects()
    new_list = [p for p in projects if p.get("id") != project_id]
    if len(new_list) < len(projects):
        save_projects_list(new_list)
        return True
    return False


def activate_project(project_id: str, docs_dir: Path | str = DEFAULT_DOCS) -> dict[str, Any] | None:
    """Define o projeto como ativo e sincroniza workspace/docs/project.json."""
    projects = list_projects()
    target = None
    for p in projects:
        if p.get("id") == project_id:
            p["status"] = "active"
            target = p
        else:
            p["status"] = "inactive"
    if not target:
        return None
    save_projects_list(projects)

    # Inicia/garante repositório e watcher do GiteaDog para o projeto ativo
    try:
        from backend.moco.gitea_manager import gitea_manager
        gitea_manager.init_project_repo(
            project_id=target.get("id", project_id),
            project_name=target.get("name", "Projeto"),
            folder_path=target.get("folder_path")
        )
    except Exception:
        pass

    prof_id = target.get("profile_id", "crm_vertical")
    vert_id = target.get("vertical_id")
    try:
        resolved = resolve_project_profile(profile_id=prof_id, vertical_id=vert_id)
        resolved["project_id_custom"] = target.get("id")
        resolved["project_name"] = target.get("name")
        resolved["project_prompt"] = target.get("prompt")
        resolved["project_agents"] = target.get("agents", [])
        resolved["project_mcps"] = target.get("mcps", [])
        resolved["project_search_apis"] = target.get("search_apis", [])
        resolved["project_automations"] = target.get("automations", [])
        save_project_profile(resolved, docs_dir=docs_dir)
        target["resolved_profile"] = resolved
    except Exception:
        pass
    return target
