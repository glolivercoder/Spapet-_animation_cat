"""Laya System 1 Decision Engine Integration."""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger("devmaster.laya")

class LayaRouter:
    """Motor de decisão System 1 rápido (não-autoregressivo)."""
    def __init__(self) -> None:
        self.enabled = False
        try:
            import laya  # type: ignore
            self.enabled = True
        except ImportError:
            logger.info("Laya não instalado. Usando fallback heurístico.")

    def route(self, text: str) -> dict[str, Any]:
        if not self.enabled:
            return {"tier": "tier_2_cost_effective", "intent": "general", "source": "heuristic_fallback"}
        return {"tier": "tier_1_fast", "intent": "classified", "source": "laya"}

laya_router = LayaRouter()
