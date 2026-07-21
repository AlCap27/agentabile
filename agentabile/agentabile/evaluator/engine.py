"""
Scoring engine generico: rubrica + evidenze -> punteggio per asse.

Non sa nulla di dove vengono le evidenze (WooCommerce, scan HTML, CSV...) né
di concetti specifici a un provider (es. "gate commerce" del SiteProvider,
vedi EVALUATOR_DESIGN.md §4 — quella logica vive in
`providers/site/scan.py`, non qui). Vedi EVALUATOR_DESIGN.md §2 per la
formula esatta.
"""
from __future__ import annotations

from agentabile.evaluator.evidence import AxisScore, Evidence, Outcome, RubricItem


def score_axis(evidences: list[Evidence], rubric: list[RubricItem], axis: str) -> AxisScore:
    """score(asse) = round(100 * Σ peso(PASS) / Σ peso(PASS ∪ FAIL)).

    NOT_APPLICABLE, UNVERIFIABLE, NOT_CHECKED sono esclusi dal denominatore.
    Se il denominatore è 0, l'asse è N/A (score=None), mai zero.
    Un RubricItem con axis="both" conta sia su "visibility" sia su
    "transactability" quando questa funzione viene chiamata per quell'asse.
    """
    weight_by_id = {item.id: item.weight for item in rubric if item.axis in (axis, "both")}

    earned = 0
    applicable = 0
    for evidence in evidences:
        weight = weight_by_id.get(evidence.requirement_id)
        if weight is None:
            continue
        if evidence.outcome == Outcome.PASS:
            earned += weight
            applicable += weight
        elif evidence.outcome == Outcome.FAIL:
            applicable += weight
        # NOT_APPLICABLE / UNVERIFIABLE / NOT_CHECKED: esclusi dal denominatore

    if applicable == 0:
        return AxisScore(axis=axis, score=None, earned_weight=0, applicable_weight=0)
    return AxisScore(
        axis=axis,
        score=round(100 * earned / applicable),
        earned_weight=earned,
        applicable_weight=applicable,
    )
