"""
Agent-Readiness Score + report di data quality per merchant.

Non valuta la conformità a un formato di export (quello lo fanno gli
exporter e `validate.py`): valuta la qualità *intrinseca* dei dati
canonici. Un prodotto senza immagine, senza descrizione o senza prezzo è
tecnicamente esportabile in ACP/Merchant Center, ma un agente non ha
abbastanza segnale per consigliarlo con sicurezza a un utente o per
rispondere a domande su di esso. Lo score è quindi un proxy di "quanto un
agente può fidarsi di questo prodotto", non di validità sintattica.

Da EVALUATOR_DESIGN.md: questo modulo è la rubrica "quality" (DQ-*),
distinta dalla rubrica AR-* verificata dal SiteProvider. I check pesati
vivono in `agentabile.evaluator.providers.catalog` (producono Evidence);
qui si delega allo scoring engine generico (`agentabile.evaluator.engine`)
per il punteggio numerico e si ricostruiscono gli Issue per il report
leggibile — firma e output numerico restano identici a prima del
refactoring (stessi pesi, stesso `_MAX_POINTS` implicito = 110).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agentabile.evaluator import engine
from agentabile.evaluator.evidence import Outcome
from agentabile.evaluator.providers import catalog as catalog_provider
from agentabile.model import Catalog, Product


@dataclass
class Issue:
    field: str
    severity: str  # "error" (blocca la fruibilità), "warning", "info"
    message: str
    points: int  # punti persi rispetto al massimo del check


@dataclass
class ProductScore:
    product_id: str
    score: int  # 0-100
    issues: list[Issue] = field(default_factory=list)


@dataclass
class CatalogReport:
    seller_name: str
    overall_score: int  # 0-100, media dei punteggi prodotto
    product_count: int
    product_scores: list[ProductScore]
    summary: dict[str, int]  # campo -> numero di prodotti con almeno un issue su quel campo


# Ogni check: (field, severity, weight, funzione(product) -> messaggio se fallisce, altrimenti None)


def score_product(p: Product) -> ProductScore:
    evidences = catalog_provider.evaluate_product(p)
    axis = engine.score_axis(evidences, catalog_provider.DQ_RUBRIC, axis="quality")
    issues = [
        Issue(
            field=e.observed["field"],
            severity=e.observed["severity"],
            message=e.detail,
            points=int(e.observed["weight"]),
        )
        for e in evidences
        if e.outcome == Outcome.FAIL
    ]
    # Ogni check DQ-* è sempre applicabile (mai N/A/unverifiable): il
    # denominatore è quindi sempre 110, axis.score non è mai None qui.
    assert axis.score is not None
    return ProductScore(product_id=p.id, score=axis.score, issues=issues)


def score_catalog(catalog: Catalog) -> CatalogReport:
    product_scores = [score_product(p) for p in catalog.products]
    overall = round(sum(ps.score for ps in product_scores) / len(product_scores)) if product_scores else 0

    summary: dict[str, int] = {}
    for ps in product_scores:
        for f_name in {issue.field for issue in ps.issues}:
            summary[f_name] = summary.get(f_name, 0) + 1

    return CatalogReport(
        seller_name=catalog.seller_name,
        overall_score=overall,
        product_count=len(product_scores),
        product_scores=product_scores,
        summary=summary,
    )


def format_report(report: CatalogReport) -> str:
    """Report leggibile per il merchant: punteggio complessivo, problemi più
    diffusi nel catalogo, poi dettaglio dei prodotti peggiori."""
    lines = [
        f"Agent-Readiness Score — {report.seller_name}",
        f"Punteggio complessivo: {report.overall_score}/100 su {report.product_count} prodotti",
        "",
    ]
    if report.summary and report.product_count:
        lines.append("Problemi più diffusi nel catalogo:")
        for f_name, count in sorted(report.summary.items(), key=lambda kv: kv[1], reverse=True):
            pct = round(100 * count / report.product_count)
            lines.append(f"  • {f_name}: {count}/{report.product_count} prodotti ({pct}%)")
        lines.append("")

    problematic = sorted((ps for ps in report.product_scores if ps.issues), key=lambda ps: ps.score)
    if problematic:
        lines.append("Prodotti con problemi (dal punteggio più basso):")
        for ps in problematic:
            lines.append(f"  [{ps.score:3d}/100] {ps.product_id}")
            for issue in ps.issues:
                lines.append(f"      - ({issue.severity}) {issue.field}: {issue.message}")
    else:
        lines.append("Nessun problema rilevato: catalogo pronto per gli agenti AI.")

    return "\n".join(lines)
