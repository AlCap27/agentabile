"""
Contratto dati tra i provider di evidenza (CatalogProvider, SiteProvider) e lo
scoring engine. Vedi EVALUATOR_DESIGN.md §2 — questo modulo è la traduzione
letterale di quel contratto, non va esteso senza aggiornare il design.

Il principio non negoziabile: l'engine (engine.py) importa solo `Evidence` e
`RubricItem` da qui, mai i provider concreti. I provider producono fatti
(Evidence), mai punteggi.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, HttpUrl


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"  # superficie condizionale non esposta -> mai zero
    UNVERIFIABLE = "unverifiable"      # fetch fallito/timeout/soft-404 ambiguo: escluso dal punteggio
    NOT_CHECKED = "not_checked"        # fuori scope v1, dichiarato, trasparente nel report


class Evidence(BaseModel):
    requirement_id: str
    outcome: Outcome
    detail: str
    checked_url: Optional[HttpUrl] = None
    observed: dict[str, str] = {}


class RubricItem(BaseModel):
    id: str  # = requirement_id atteso
    name: str
    axis: Literal["visibility", "transactability", "both", "quality"]
    weight: int
    strength: Optional[Literal["MUST", "SHOULD", "MAY"]] = None


class AxisScore(BaseModel):
    axis: str
    score: Optional[int] = None  # 0-100; None = intero asse N/A
    earned_weight: int
    applicable_weight: int


class ScanReport(BaseModel):
    target: HttpUrl
    spec_version: str
    scanned_at: datetime
    pages_fetched: int
    axes: list[AxisScore]
    evidences: list[Evidence]
    top_issues: list[Evidence]
    limits: list[str] = []
