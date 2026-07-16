"""
Agent-Readiness Score + report di data quality per merchant.

Non valuta la conformità a un formato di export (quello lo fanno gli
exporter e `validate.py`): valuta la qualità *intrinseca* dei dati
canonici. Un prodotto senza immagine, senza descrizione o senza prezzo è
tecnicamente esportabile in ACP/Merchant Center, ma un agente non ha
abbastanza segnale per consigliarlo con sicurezza a un utente o per
rispondere a domande su di esso. Lo score è quindi un proxy di "quanto un
agente può fidarsi di questo prodotto", non di validità sintattica.

Ogni check ha un peso; lo score di un prodotto è
`100 * (max_points - punti persi) / max_points`, aggregato su tutto il
catalogo come media. `format_report` produce un report leggibile per il
merchant, con i problemi più diffusi in cima.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from agentready.model import Catalog, Product

_TAG_RE = re.compile(r"<[^>]+>")


def _plain_len(text: str | None) -> int:
    if not text:
        return 0
    return len(_TAG_RE.sub(" ", text).strip())


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


def _check_title(p: Product) -> tuple[str, str, int, str] | None:
    if not p.title or len(p.title.strip()) < 3:
        return ("title", "error", 15, "Titolo mancante o troppo corto per essere utile a un agente")
    return None


def _check_description(p: Product) -> tuple[str, str, int, str] | None:
    if max(_plain_len(p.description_plain), _plain_len(p.description_html)) < 20:
        return (
            "description", "warning", 15,
            "Descrizione assente o troppo breve (<20 caratteri): poco contesto per un agente",
        )
    return None


def _check_brand(p: Product) -> tuple[str, str, int, str] | None:
    if not p.brand:
        return ("brand", "info", 5, "Brand mancante — utile per matching cross-piattaforma e fiducia dell'agente")
    return None


def _check_category(p: Product) -> tuple[str, str, int, str] | None:
    if not p.categories:
        return ("categories", "warning", 10, "Nessuna categoria — l'agente non può posizionare il prodotto in una ricerca per categoria")
    return None


def _check_media(p: Product) -> tuple[str, str, int, str] | None:
    if not p.media and not any(v.media for v in p.variants):
        return ("media", "error", 15, "Nessuna immagine su prodotto o varianti — molte superfici agent (ACP, Google) la richiedono")
    return None


def _check_url(p: Product) -> tuple[str, str, int, str] | None:
    if not p.url and not (p.variants and all(v.url for v in p.variants)):
        return ("url", "warning", 10, "Nessun link alla pagina prodotto — l'agente non può indirizzare l'utente all'acquisto")
    return None


def _check_price(p: Product) -> tuple[str, str, int, str] | None:
    unpriced = [v.id for v in p.variants if v.price is None]
    if unpriced:
        return (
            "price", "error", 20,
            f"{len(unpriced)}/{len(p.variants)} varianti senza prezzo: un agente non può proporre un acquisto ({', '.join(unpriced[:3])}{'...' if len(unpriced) > 3 else ''})",
        )
    return None


def _check_barcode(p: Product) -> tuple[str, str, int, str] | None:
    missing = [v.id for v in p.variants if not v.barcodes]
    if missing:
        return (
            "barcode", "info", 5,
            f"{len(missing)}/{len(p.variants)} varianti senza barcode (GTIN/EAN/UPC) — consigliato per il matching cross-piattaforma",
        )
    return None


def _check_variant_options(p: Product) -> tuple[str, str, int, str] | None:
    if len(p.variants) > 1:
        missing = [v.id for v in p.variants if not v.options]
        if missing:
            return (
                "variant_options", "warning", 10,
                f"{len(missing)}/{len(p.variants)} varianti senza opzioni (es. colore/taglia): l'agente non può distinguerle o spiegarne la differenza",
            )
    return None


def _check_availability_quantity(p: Product) -> tuple[str, str, int, str] | None:
    incomplete = [v.id for v in p.variants if v.availability.status.value == "in_stock" and v.availability.quantity is None]
    if incomplete:
        return (
            "availability", "info", 5,
            f"{len(incomplete)}/{len(p.variants)} varianti 'in_stock' senza quantità: l'agente non può rispondere a 'quante ne avete disponibili'",
        )
    return None


_CHECKS = [
    _check_title, _check_description, _check_brand, _check_category,
    _check_media, _check_url, _check_price, _check_barcode,
    _check_variant_options, _check_availability_quantity,
]
_MAX_POINTS = 110  # somma dei pesi dei check sopra — non serve farla tornare a 100 a mano


def score_product(p: Product) -> ProductScore:
    issues: list[Issue] = []
    for check in _CHECKS:
        result = check(p)
        if result is not None:
            f_name, severity, points, message = result
            issues.append(Issue(field=f_name, severity=severity, message=message, points=points))
    lost = sum(i.points for i in issues)
    score = max(0, round(100 * (_MAX_POINTS - lost) / _MAX_POINTS))
    return ProductScore(product_id=p.id, score=score, issues=issues)


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
