"""
backend/moco/mcp_broker.py
Roteamento Inteligente de MCPs (Tool-Forge) e Port Broker Automatizado (Padrão MOCO).
Evita explosão de contexto por injeção excessiva de ferramentas e previne colisões de portas locais.
"""
from __future__ import annotations

import socket
import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Mapeamento de Lazy Loading de MCPs por fase operacional
PHASE_MCP_MAP: Dict[str, List[str]] = {
    "MARKET_RESEARCH": ["browse-user", "brave-search", "serpapi"],
    "CRITICAL_ANALYSIS": ["browse-user"],
    "ARCHITECT_WORKTREE": ["opencode", "gitea", "filesystem"],
    "CODER_TESTER": ["opencode", "playwright", "gitea", "reui"],
    "UI_FRONTEND_DESIGN": ["reui", "figma", "21dev"],
    "DEPLOY_INFRA": ["coolify", "vercel", "docker", "supabase"],
}

DEFAULT_MAX_MCPS: int | None = None


class MCPBroker:
    @staticmethod
    def filter_mcps_for_phase(phase: str, max_mcps: int | None = DEFAULT_MAX_MCPS) -> List[str]:
        """
        Retorna as ferramentas MCP necessárias para a fase operacional.
        Sem limitação artificial por padrão (livre para o usuário e orquestrador).
        Permite teto opcional se especificado explicitamente.
        """
        phase_key = phase.upper()
        allowed = PHASE_MCP_MAP.get(phase_key, ["opencode"])
        if max_mcps is not None and max_mcps > 0:
            return allowed[:max_mcps]
        return list(allowed)

    @staticmethod
    def get_all_supported_phases() -> List[str]:
        return list(PHASE_MCP_MAP.keys())


class PortBroker:
    def __init__(self):
        self.allocated_ports: Dict[str, int] = {}

    @staticmethod
    def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
        """Verifica de forma rápida e segura se a porta TCP está livre para bind."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                # Se connect_ex retornar 0, porta está aberta (ocupada)
                result = s.connect_ex((host, port))
                return result != 0
        except Exception:
            return False

    def find_available_port(self, preferred_port: int, max_attempts: int = 15, host: str = "127.0.0.1") -> int:
        """Encontra a primeira porta livre a partir da porta preferencial."""
        candidate = preferred_port
        for _ in range(max_attempts):
            if candidate not in self.allocated_ports.values() and self.is_port_free(candidate, host):
                return candidate
            candidate += 1
        return candidate

    def reserve_port(self, service_name: str, preferred_port: int, host: str = "127.0.0.1") -> int:
        """Reserva uma porta sem colisão para o serviço solicitado."""
        free_port = self.find_available_port(preferred_port, host=host)
        self.allocated_ports[service_name] = free_port
        logger.info(f"[PortBroker] Serviço '{service_name}' alocado na porta {free_port} (preferencial: {preferred_port})")
        return free_port

    def release_port(self, service_name: str) -> Optional[int]:
        return self.allocated_ports.pop(service_name, None)

    def get_allocations(self) -> Dict[str, int]:
        return dict(self.allocated_ports)

