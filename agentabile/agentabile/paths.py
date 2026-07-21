"""Percorsi di risorse vendorizzate del pacchetto, risolti relativamente
alla posizione del pacchetto stesso — funziona anche in editable install
(pip install -e), dove il codice resta letto dal checkout originale.
Usato da consumer esterni al repo (es. il repo privato dell'Evaluator)
che non possono più calcolare `schemas/` relativo al proprio file."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
AGENTREADY_SPEC_PATH = SCHEMAS_DIR / "agentready.spec.json"
