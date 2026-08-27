# Agentabile Evaluator — Design v1 (Fase 1)

> Documento di design per lo scan gratuito di agentabile.dev.
> Spec normativa: **AgentReady 1.0.0 (2026-04-24)** — `https://www.agentready.org/spec.json`,
> 30 requisiti in 5 sezioni. Ogni requisito è citato tramite `stableId` (AR-*).
> Stato: **in attesa di approvazione di Alex — non procedere alla Fase 2 senza approvazione esplicita.**

---

## 1. Architettura: due evidence provider, un solo scoring engine

```
CatalogProvider (esistente)          SiteProvider (nuovo)
  consuma Catalog canonico             fetch HTML statico + parsing
  (plugin WP / CLI / connettori)       (scan gratuito da URL)
        │                                     │
        └────────► list[Evidence] ◄───────────┘
                        │
                 Scoring Engine
          (rubrica + evidenze → punteggi)
                        │
                   ScanReport
        (2 assi, N/A espliciti, top-3 issue)
```

Principio non negoziabile: **lo scoring engine non sa da dove viene l'evidenza**.
Il confine è imposto a livello di moduli: l'engine importa solo `Evidence` e
`RubricItem`, mai i provider. I provider non calcolano punteggi, producono fatti.

Struttura proposta (dentro il pacchetto Python esistente):

```
agentabile/evaluator/
  evidence.py          # contratto dati (Evidence, RubricItem, ScanReport)
  engine.py            # scoring generico rubrica+evidenze
  rubric_ar.py         # rubrica AR-* costruita da spec.json vendorizzato
  providers/
    catalog.py         # adapter sopra score.py esistente (zero regressioni)
    site/
      fetcher.py       # HTTP, robots.txt, rate limit, budget
      checks.py        # un check per requisito AR-* verificabile
```

### Rapporto con il codice esistente (cosa è riusabile come rubrica)

`score.py` oggi valuta **qualità dei dati di catalogo** (titolo, prezzo,
immagini…): non sono requisiti AR-* e non vanno forzati nella mappa AR-*.
Restano una rubrica separata (`DQ-*`, asse "quality") consumata dallo stesso
engine tramite il `CatalogProvider`. Ciò che si riusa di `score.py` è il
**pattern** (check pesati → issue con severità → report ordinato per problemi
più diffusi), non i check.

Vincolo di refactoring: `score_product` / `score_catalog` / `format_report`
mantengono firma e **output numerico identico** (stessi pesi, stesso
`_MAX_POINTS`): internamente delegano a engine+adapter. Il plugin WordPress
in produzione non è toccato (è PHP puro, non dipende da questo codice; il
vincolo vale per la CLI/motore Python).

Lo **scan gratuito usa solo il SiteProvider**. Il CatalogProvider continua a
servire il percorso plugin/CLI; l'incrocio dei due (report a pagamento) è
esplicitamente fuori scope.

---

## 2. Contratto dati SiteProvider ↔ engine (schema Pydantic)

```python
class Outcome(str, Enum):
    PASS = "pass"                    # requisito verificato e soddisfatto
    FAIL = "fail"                    # applicabile ma non soddisfatto
    NOT_APPLICABLE = "not_applicable"  # superficie condizionale non esposta → mai zero
    UNVERIFIABLE = "unverifiable"    # fetch fallito/timeout/soft-404 ambiguo: escluso dal punteggio
    NOT_CHECKED = "not_checked"      # fuori scope v1 (dichiarato, trasparente nel report)

class Evidence(BaseModel):
    requirement_id: str              # stableId AR-* (o DQ-* per la rubrica catalogo)
    outcome: Outcome
    detail: str                      # perché, umano-leggibile, in italiano
    checked_url: Optional[HttpUrl]   # risorsa ispezionata (es. https://sito/.well-known/ucp)
    observed: dict[str, str] = {}    # fatti grezzi: status_code, content_type, snippet ≤ 200 char

class RubricItem(BaseModel):
    id: str                          # = requirement_id atteso
    name: str
    axis: Literal["visibility", "transactability", "both", "quality"]
    weight: int                      # da strength: MUST=8, SHOULD=4, MAY=1
    strength: Optional[Literal["MUST", "SHOULD", "MAY"]]

class AxisScore(BaseModel):
    axis: str
    score: Optional[int]             # 0–100; None = intero asse N/A (mai zero fuorviante)
    earned_weight: int
    applicable_weight: int

class ScanReport(BaseModel):
    target: HttpUrl
    spec_version: str                # es. "1.0.0" — sempre mostrata nel report
    scanned_at: datetime
    pages_fetched: int
    axes: list[AxisScore]            # AI Visibility, Agent Transactability
    evidences: list[Evidence]        # tutte, incluse N/A e not_checked
    top_issues: list[Evidence]       # i 3 FAIL a peso più alto (scan gratuito)
    limits: list[str]                # es. "contenuto principale richiede JavaScript",
                                     #     "robots.txt limita la scansione a N pagine"
```

Regole di punteggio per asse:

```
score(asse) = round(100 * Σ peso(PASS) / Σ peso(PASS ∪ FAIL))
```

- `NOT_APPLICABLE`, `UNVERIFIABLE`, `NOT_CHECKED` sono **esclusi dal
  denominatore** — non penalizzano mai.
- Se il denominatore di un asse è 0 (es. sito non e-commerce →
  Transactability) l'asse è `score = None` e il report mostra **"N/A"** con la
  spiegazione, **mai 0**. Vincolo esplicito, verificato da test in Fase 2.
- Item con `axis = "both"` contano in entrambi i denominatori, **ma il
  denominatore di Transactability esiste solo se il gate commerce è aperto**
  (v. §4): su un sito non-commerce un item "both" conta solo su Visibility.
- Pesi: MUST=8, SHOULD=4, MAY=1. I MAY restano nel denominatore ma con impatto
  minimo: 100/100 significa "pienamente agent-ready, anche sugli opzionali".
  I requisiti `emerging` non hanno peso diverso, solo un badge nel report.

---

## 3. Mappa completa requisito → asse → metodo di verifica (fetch statico)

Legenda assi: **V** = AI Visibility, **T** = Agent Transactability.
"→ N/A" = quando la superficie condizionale non è rilevabile, l'esito è
`NOT_APPLICABLE` (mai FAIL, mai zero).

### Discoverability

| ID | Strength | Asse | Verifica v1 |
|---|---|---|---|
| AR-DISC-01 robots.txt con AI policy | MUST | V | GET `/robots.txt`. FAIL se assente; FAIL (con dettaglio distinto) se presente ma senza regole per nessuno UA AI noto (GPTBot, ClaudeBot, Google-Extended, PerplexityBot, …). |
| AR-DISC-02 sitemap | SHOULD | V | Direttiva `Sitemap:` in robots.txt **oppure** GET `/sitemap.xml`; PASS se raggiungibile e XML valido (anche sitemap index). |
| AR-DISC-03 llms.txt | SHOULD | V | GET `/llms.txt`: 200, contenuto testuale/markdown non vuoto, non una pagina HTML (guardia soft-404, v. §5). |
| AR-DISC-04 llms-full.txt | MAY | V | GET `/llms-full.txt`, stesso criterio. |
| AR-DISC-05 HTTP Link header | MAY | V | Ispezione header della risposta homepage: `Link` con rel `sitemap` / `describedby` / `api-catalog` / `alternate`. |
| AR-DISC-06 NLWeb schema feeds | MAY, cond. | V | Direttiva `schemamap` in robots.txt → PASS. Assente → **N/A** (non si può stabilire staticamente che il sito "offra search"). |

### Content for agents

| ID | Strength | Asse | Verifica v1 |
|---|---|---|---|
| AR-CONT-01 JSON-LD | SHOULD | V | extruct sulle pagine scaricate: PASS se ≥1 entità schema.org significativa (Organization, Product, Offer, FAQPage, SoftwareApplication…). I tipi trovati alimentano anche il rilevamento della superficie commerce (§4). |
| AR-CONT-02 markdown negotiation | MAY | V | Seconda GET della homepage con `Accept: text/markdown`: PASS se risposta `text/markdown`. |
| AR-CONT-03 /index.md | MAY | V | GET `/index.md`: 200 + markdown (guardia soft-404). |
| AR-CONT-04 speakable | MAY, cond. | V | `SpeakableSpecification` nel JSON-LD → PASS. Assente → **N/A** (l'intento "contenuto per voice agent" non è verificabile staticamente). |

### Capabilities

| ID | Strength | Asse | Verifica v1 |
|---|---|---|---|
| AR-CAPA-01 MCP | MUST, cond. | V | Solo rilevamento passivo di dichiarazioni: server card (CAPA-02), ai-plugin.json che referenzia MCP, endpoint MCP citato in llms.txt. Segnale trovato → PASS; nessun segnale → **N/A**. Nessun handshake JSON-RPC attivo in v1. |
| AR-CAPA-02 MCP Server Card | SHOULD, cond. | V | GET `/.well-known/mcp/server-card.json`: JSON valido → PASS. Se altri segnali MCP esistono ma la card manca → FAIL; nessun segnale MCP → **N/A**. |
| AR-CAPA-04 A2A Agent Card | MUST, cond. | V | GET `/.well-known/agent-card.json`: JSON valido con campi identità/endpoint → PASS; assente → **N/A**. |
| AR-CAPA-08 OpenAPI | MUST, cond. | V | Se `/.well-known/api-catalog` (IDEN-06) o Link header puntano a descrittori → segui il link (nel budget) e verifica documento OpenAPI. In aggiunta probe di `/openapi.json` e `/swagger.json`. Nessun segnale di API → **N/A**. |
| AR-CAPA-09 ai-plugin.json | MAY, cond. | V | GET `/.well-known/ai-plugin.json`: JSON valido → PASS; assente → **N/A**. |
| AR-CAPA-03 MCP Apps | MAY | — | **NOT_CHECKED in v1** (richiede sessione MCP attiva). |
| AR-CAPA-05 WebMCP | MAY | — | **NOT_CHECKED in v1** (richiede runtime JS — vietato da vincolo no-headless). |
| AR-CAPA-06 NLWeb /ask | MAY | — | **NOT_CHECKED in v1** (richiederebbe probing attivo di un endpoint di query). |
| AR-CAPA-07 Agent Skills | MAY | — | **NOT_CHECKED in v1** (nessuna convenzione di discovery per siti web). |

### Identity & Access

| ID | Strength | Asse | Verifica v1 |
|---|---|---|---|
| AR-IDEN-01 Web Bot Auth | SHOULD, baseline | **both** (T solo con gate commerce aperto, v. §4) | GET `/.well-known/http-message-signatures-directory`: PASS/FAIL (baseline: applicabile a tutti, quindi conta **sempre** su V). Su T conta solo se è rilevata una superficie commerce: senza qualcosa da comprare, identificare il traffico agente è una questione di lettura (V), non di checkout. Emerging: quasi tutti i siti oggi falliranno — peso SHOULD=4, dettaglio non allarmistico. |
| AR-IDEN-02 OAuth 2.0 | MUST, cond. | T | Applicabile solo se rilevato un authorization server (metadata IDEN-03 presenti) **o** superficie API + area utenti. In quel caso: metadata raggiungibili → PASS. Nessun segnale → **N/A** (un e-commerce con soli account classici non viene punito). |
| AR-IDEN-03 OAuth AS Metadata | MUST, cond. | T | GET `/.well-known/oauth-authorization-server` e `/.well-known/openid-configuration`: JSON valido con `issuer`+endpoint → PASS; assenti → **N/A**. |
| AR-IDEN-05 PKCE | MUST, cond. | T | Solo se i metadata IDEN-03 esistono: `code_challenge_methods_supported` include `S256` → PASS, altrimenti FAIL. Senza metadata → **N/A**. |
| AR-IDEN-04 OAuth Protected Resource | SHOULD, cond. | T | GET `/.well-known/oauth-protected-resource`: presente → PASS; assente senza altri segnali OAuth → **N/A**; assente ma AS rilevato → FAIL. |
| AR-IDEN-06 API Catalog | MAY, cond. | V | GET `/.well-known/api-catalog`: linkset valido → PASS; assente → **N/A** (se nessun'altra API rilevata) o FAIL (se API rilevata via CAPA-08). |

### Commerce (tutte T; approcci alternativi per la spec)

La spec definisce i requisiti Commerce come **alternativi**: si è conformi
implementandone almeno uno applicabile. Sommarli sarebbe scorretto. Quindi:

- Item sintetico **`AR-COMM-ANY`** ("acquisto agentico possibile"), peso 8
  (equivalente MUST, coerente con il linguaggio di conformance della spec).
  PASS se ≥1 protocollo commerce rilevato; FAIL se superficie commerce
  presente ma nessun protocollo; **N/A se il sito non è un e-commerce**
  (→ intero asse T **sempre** N/A per effetto del gate di §4).
- I singoli protocolli compaiono nel report come righe **informative** (peso
  0), così il merchant vede cosa esiste nel panorama:

| ID | Verifica v1 |
|---|---|
| AR-COMM-04 UCP | GET `/.well-known/ucp`: profilo valido → rilevato. Unico protocollo con discovery well-known standard: check affidabile. |
| AR-COMM-02 ACP | Nessuna discovery standardizzata: probe euristico di convenzioni note di feed ACP, incluso l'endpoint del plugin Agentabile (`/wp-json/agentabile/v1/feed/acp`). Dichiarato "euristico" nel report. |
| AR-COMM-01 x402 | **NOT_CHECKED in v1** (richiederebbe provocare risposte 402). |
| AR-COMM-03 ACP Delegate Payment | **NOT_CHECKED in v1** (si applica a payment provider, non ai siti scansionati). |
| AR-COMM-05 MPP | **NOT_CHECKED in v1** (basato su 402, stesso motivo di x402). |

---

## 4. Rilevamento della superficie commerce (gate di applicabilità)

L'asse Transactability e `AR-COMM-ANY` sono applicabili solo se il sito è un
e-commerce. Rilevamento statico, in ordine di affidabilità:

1. JSON-LD `Product` con `Offer` (da CONT-01) su una pagina scansionata;
2. fingerprint di piattaforma (WooCommerce: `wp-content/plugins/woocommerce`,
   `/?wc-ajax=`; Shopify: `cdn.shopify.com`; PrestaShop, Magento…);
3. link a percorsi carrello/checkout (`/cart`, `/checkout`, `/carrello`,
   `/my-account`) nell'HTML delle pagine scansionate.

Nessun segnale → sito trattato come non-commerce → il gate è **chiuso** e
l'asse Transactability è **sempre `N/A`**, con testo: *"Non abbiamo rilevato
una superficie e-commerce: questo asse non si applica"*. Test obbligatorio in
Fase 2 (sito editoriale → N/A, non 0).

**Decisione di review (2026-07-21, sollevata da Alex): il gate agisce a
livello di asse, non solo su AR-COMM-ANY.** Il problema: AR-IDEN-01 (Web Bot
Auth) è baseline e marcato "both"; senza gate d'asse, un sito non-commerce
avrebbe avuto un punteggio T calcolato dal solo IDEN-01 — quasi sempre 0/100
su un unico requisito SHOULD emergente, cioè esattamente lo "zero fuorviante"
che il design vieta. Decisione: quando il gate è chiuso, **tutti** gli item
dell'asse T (inclusi quelli "both") non contribuiscono al denominatore T;
IDEN-01 resta valutato e conta su V, dove appartiene comunque (identificare il
traffico agente in lettura). L'alternativa scartata — tenere IDEN-01 su T
incondizionatamente e spiegarlo nel report — avrebbe presentato come "punteggio
di transactability" un numero privo di segnale sull'acquisto agentico.
Conseguenza semantica accettata: un T numerico esiste solo per siti con
superficie commerce; su tutti gli altri il report mostra N/A senza eccezioni.

---

## 5. Perimetro di crawling (vincoli recepiti, non riaperti)

- **User-Agent**: `AgentabileBot/1.0 (+https://agentabile.dev/bot)` su ogni
  richiesta. La pagina `/bot` (Fase 2, contenuto statico) spiega scopo e
  contatti.
- **robots.txt**: rispetto integrale (parser `protego`, supporta wildcard),
  valutato per `AgentabileBot` e `*`, **su tutti i percorsi inclusi i
  `/.well-known/*`**. Se robots.txt nega tutto → lo scan si ferma e il report
  dice chiaramente "il sito non consente la scansione" (nessun punteggio
  parziale inventato). `Crawl-delay` rispettato se > del nostro rate limit.
- **Rate limit**: 1 req/s, client sincrono a esecuzione seriale (il rate limit
  rende inutile la concorrenza — semplicità prima di tutto).
- **Budget**: max **25 pagine HTML** + ~15 probe leggere (robots, sitemap,
  llms*, well-known, canary). Hard cap complessivo: 45 richieste, 15 MB di
  banda totale, 2 MB per risposta (streaming con troncamento), timeout 10 s
  per richiesta, durata massima scan ~120 s. A 1 req/s uno scan tipico dura
  40–60 s: **il frontend deve trattarlo come job asincrono con progresso**.
- **Selezione pagine** nel budget: homepage → sitemap (se presente) →
  priorità a 1 pagina prodotto, 1 pagina contenuto/about, 1 pagina docs; il
  resto solo se serve (25 è un tetto, non un obiettivo: scan tipico 8–12
  pagine).
- **Guardia soft-404**: 1 probe a un percorso random (es.
  `/agentabile-canary-<uuid>`); se risponde 200, i check "file presente/
  assente" diventano `UNVERIFIABLE` invece di dare falsi PASS.
- **Niente** bypass di login/paywall; **nessun dato personale** raccolto: si
  salvano solo esiti, header rilevanti e snippet ≤ 200 caratteri di file
  tecnici.
- **No headless browser** (vincolo di design, non rivalutabile in Fase 2): se
  la homepage ha testo estratto sotto soglia (~200 caratteri) con bundle JS
  presenti, il fatto entra in `ScanReport.limits` come **segnale
  diagnostico**: *"il contenuto principale non è visibile a un fetch semplice
  — gli agenti che non eseguono JavaScript non lo vedono"*. È un finding di
  valore per il merchant, non un ostacolo da aggirare.

---

## 6. Stack: validazione della proposta

| Componente | Scelta | Motivazione |
|---|---|---|
| Fetch | **httpx** | Confermato. Timeout granulari, controllo redirect, HTTP/2; client sincrono (v. rate limit). |
| Parsing HTML | **selectolax** | Confermato. Veloce e tollerante; serve per link, fingerprint, estrazione testo (segnale JS). |
| Dati strutturati | **extruct** (solo sintassi `json-ld` + `microdata`) | Confermato con perimetro: il target sono PMI con temi WooCommerce spesso datati, dove il markup prodotto è ancora microdata. RDFa/opengraph disattivati. Porta lxml come dipendenza: accettabile. |
| robots.txt | **protego** (aggiunta) | `urllib.robotparser` non gestisce bene wildcard e `Crawl-delay`; protego è il parser di Scrapy, battle-tested. |
| Schema dati | **pydantic v2** | Già in uso nel progetto (model.py). |

Spec vendorizzata: `agentabile/schemas/agentready.spec.json` (copia della
1.0.0) + script di refresh dall'URL canonico. A runtime lo scan usa la copia
vendorizzata (deterministico, nessuna dipendenza di rete dalla spec); un check
in CI segnala se l'upstream ha cambiato versione. La rubrica è costruita
**dal file spec.json** (stableId, strength, applies, emerging) — mai
trascritta a mano; solo l'assegnazione asse→requisito e il metodo di verifica
vivono nel codice (`rubric_ar.py`), chiavati per stableId così un MINOR bump
della spec che aggiunge requisiti produce un warning esplicito ("requisito
non mappato") invece di rompere.

---

## 7. Report dello scan gratuito

- Intestazione: URL, data, **"valutato rispetto ad AgentReady 1.0.0"**.
- **Due punteggi separati**: AI Visibility Score e Agent Transactability
  Score, ciascuno 0–100 **oppure "N/A" con spiegazione** (mai zero
  fuorviante).
- **3 problemi principali in evidenza**: i FAIL a peso più alto, col
  `detail` umano-leggibile e il riferimento AR-* cliccabile (campo `anchor`
  della spec).
- Dettaglio completo per sezione: PASS / FAIL / N/A / non verificabile /
  fuori scope v1, ognuno col perché. Trasparenza totale su cosa non è stato
  controllato.
- `limits` in chiaro (JS richiesto, robots restrittivo, pagine troncate).

## 8. Cosa NON viene implementato in v1 (elenco esplicito)

1. **AR-CAPA-03 (MCP Apps)**, **AR-CAPA-05 (WebMCP)**, **AR-CAPA-06 (NLWeb
   /ask)**, **AR-CAPA-07 (Agent Skills)**, **AR-COMM-01 (x402)**,
   **AR-COMM-03 (ACP Delegate Payment)**, **AR-COMM-05 (MPP)** — tutti MAY,
   bassa priorità, non verificabili con fetch statico passivo. Compaiono nel
   report come `not_checked`, esclusi dal punteggio.
2. Handshake MCP/A2A attivo (si verifica solo la discovery dichiarata).
3. Headless browser, in qualunque forma.
4. Report a pagamento, refinement, incrocio SiteProvider×CatalogProvider.
5. Storage utenti/andamento storico degli scan; lo scan gratuito è stateless
   (si valuta dopo aver visto il comportamento reale su siti veri).

## 9. Stima di sforzo (giornate di sviluppo, Fase 2)

| Componente | Stima |
|---|---|
| 1. Refactoring engine (evidence abstraction, zero regressioni su score.py — output numerico identico verificato da test) | 0,5–1 g |
| 2. Fetch layer (robots/protego, rate limit, budget, canary, UA) | 1 g |
| 3. Check AR-* (probe well-known, parsing, JSON-LD, fingerprint commerce) | 1,5–2 g |
| 4. Rubrica da spec.json + scoring due assi + gestione N/A | 0,5 g |
| 5. Generatore report (2 assi, top-3, limits) | 0,5 g |
| 6. Frontend minimo (form URL → job asincrono → report; riuso pattern PoliSim se applicabile — da chiedere prima) | 0,5–1 g |
| 7. Verifica obbligatoria su 3 siti reali + correzioni | 0,5–1 g |
| **Totale** | **~5–7 g** |

## 10. Rischi e punti aperti (da decidere in review, non bloccanti)

- **Punteggi bassi quasi ovunque su Transactability** (UCP/ACP hanno adozione
  minima oggi): è coerente con la realtà e col funnel ("ecco il gap"), ma il
  copy del report deve inquadrarlo come "acquisto *agentico*", non come
  bocciatura dell'e-commerce. Da curare in Fase 2.
- **WAF/anti-bot** che bloccano `AgentabileBot`: gli esiti diventano
  `UNVERIFIABLE` e il report lo dichiara; nessun tentativo di evasione.
- **Pesi 8/4/1**: scelta di design semplice; se in review Alex preferisce
  MAY fuori dal denominatore (score solo su MUST+SHOULD), il cambio è una
  costante, non un refactoring.

---

*Fine Fase 1. Questo documento va approvato da Alex prima di qualunque
implementazione (Fase 2, sessione separata, /model sonnet).*

---

## Addendum post-approvazione (Fase 2, 2026-07-21)

Il contenuto sopra resta il design approvato, non riaperto. Gli
scostamenti numerici e i limiti emersi implementando (budget probe,
gestione errore di rete su robots.txt, natura euristica hard-coded
dell'applicabilità condizionale, 5 check Capability/Identity che non
possono strutturalmente restituire FAIL in v1) sono documentati con il
dettaglio tecnico in `agentabile/README.md`, sezione "Evaluator — scan
gratuito", per non duplicare contenuto tra i due file.

### Nota (2026-08-27): flag di affidabilità solo nel layer API del repo privato

Il repo privato `Agentabile-Evaluator-private` (SiteProvider) calcola
un segnale di affidabilità basato sulla quota di richieste fallite per
errore di rete durante uno scan (`network_error_ratio`, soglia 20% →
`reliable=False`). Oggi vive solo nel layer API di quel repo
(`app.py`, stesso pattern già usato per `commerce_gate_open`:
post-processing sul dict dopo `model_dump()`), non come campo di
`ScanReport` qui — chi chiama `run_site_scan()` direttamente (CLI,
libreria, non tramite l'API) vede solo la riga di testo libero in
`limits`, non un booleano strutturato.

Se in futuro emerge un consumer diretto della libreria che ha bisogno
del flag strutturato, va promosso a campo vero di `ScanReport` (§2),
aggiornando questo documento come previsto dal commento in testa a
`evidence.py` ("contratto... non va esteso senza aggiornare il
design"). Nota di tracciamento, nessuna implementazione qui.
