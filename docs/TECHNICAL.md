# Technical notes


In last-mile logistics roughly 10% of shipments hit delivery exceptions: failed
attempts, address mismatches, damaged packages, refused deliveries, weather
delays. Each one costs a reattempt, and repeat failures cost the customer
relationship. This service automates the exception desk: it reads raw driver
scan logs, filters noise, decides a resolution against the operations playbook,
drafts the customer notification in the right channel and tone, and escalates
to a supervisor exactly when the playbook says so.

```
 delivery_logs.csv          customers.db / lockers          playbook.md
        |                            |                           |
  +-----v-----+   exception   +------v------+   decision   +-----v------+
  |  triage   | ------------> | resolution  | -----------> | communica- |
  |  dedupe   |               | agent       |              | tion agent |
  |  noise    |               | LLM proposes|              | LLM drafts |
  |  injection|               | rules decide|              | validator  |
  +-----------+               +------un-----+              | checks     |
        |                            |                     +-----+------+
     discard                    escalation                       |
   (logged why)                 rule engine                 SQLite store
                                                          metrics + eval
```

## How decisions are made

**Triage.** Duplicate scans are dropped (both via the upstream flag and a
content check: same shipment, status, note and attempt within 10 minutes).
DELIVERED and depot SCANNED rows are filtered as noise. Driver notes are
screened against prompt-injection patterns; a flagged note is still processed
but marked for review, and notes are always passed to the LLM as data, never
as instructions.

**Resolution.** The LLM proposes, the rule engine has the final say. A deterministic
rule engine implements the playbook: damage severity grading (with the fragile
one-level bump), the 4-hour perishable weather threshold, locker eligibility
(size vs capacity, FULL/LIMITED status, same-or-adjacent zip, never
perishables), attempt-count handling, and the full escalation matrix (third
attempt, VIP with 3+ exceptions in 90 days, damaged perishables, fraud
signals, safety reports, plus the discretionary triggers). When DeepSeek is
configured, the model gets the case plus BM25-retrieved playbook sections and
proposes a resolution with reasoning; hard escalation triggers are enforced in
code regardless of what the model says, and every override is recorded on the
case. Without a key, the rules run alone; the pipeline never blocks on the LLM.

**Communication.** Channel and tone follow the customer profile (VIP/Premium
get formal email, Standard gets casual SMS). A validator checks every draft
for the playbook's required elements: what happened, the resolution, next
steps, an apology, locker details on reroutes, and acknowledgment of an active
service credit. An LLM draft that fails validation gets one critic-driven
revision, then falls back to a template that always passes.

**Retrieval.** The playbook is chunked by section and indexed with BM25
(implemented in-repo, ~60 lines, no vector DB dependency for a 9-section
document). `GET /playbook/search?q=damaged perishable` shows what the
resolution agent sees.

**Caching.** All LLM calls go through an LRU+TTL response cache
keyed on the full request (model, messages, temperature). Hit/miss counters
are exposed at `/metrics`; the `cached` flag on a case is set only when a call
actually came from the cache. Temperature 0 makes repeated identical events
(a batch reprocess, duplicate-heavy feeds) real cache hits.

**Persistence.** Every case lands in SQLite with its full decision trail;
metrics survive restarts.

## Evaluation

`ground_truth.csv` labels all 13 log rows (exception vs noise/duplicate,
expected resolution, tone, escalation). `POST /evaluate` runs the pipeline
against it:

| metric | baseline (rules only) |
|---|---|
| noise/dedup accuracy | 1.00 |
| resolution accuracy | 1.00 |
| escalation accuracy | 1.00 |
| tone accuracy | 1.00 |
| task completion | 1.00 |

The 100% baseline is intentional: the playbook is fully
encoded, so the LLM adds judgment on messy free text and natural-language
drafting on top of a floor that cannot regress. The same harness scores the
LLM-assisted path, so any model or prompt change is measurable.

## API

| endpoint | purpose |
|---|---|
| `POST /process` | run the pipeline over all delivery log rows |
| `POST /process/{shipment_id}` | process one shipment's rows |
| `GET /cases?shipment_id=` | decision trails and customer messages |
| `GET /metrics` | case metrics plus LLM cache hit rate |
| `POST /evaluate` | score against ground truth |
| `GET /playbook/search?q=` | BM25 retrieval debug view |
| `GET /health` | service and LLM availability |

## Run

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
export DEEPSEEK_API_KEY=sk-...        # optional; rules-only without it
./venv/bin/python main.py             # API on :8010

# ops console
# dashboard deps are in requirements.txt
./venv/bin/python -m streamlit run dashboard.py
```

Tests: `./venv/bin/python -m pytest -q` (23 tests: policy rules, triage,
injection screening, cache behavior, end-to-end pipeline, API, evaluation).
CI runs them on every push. `Dockerfile` builds the API image.
`scripts/generate_data.py 500` produces synthetic logs for volume testing.

## Data

`data/` carries the operational inputs: `delivery_logs.csv` (driver scans, 13
rows incl. duplicates and noise), `customers.db` (SQLite: customer tiers,
exception history, credits; locker locations and capacity),
`ground_truth.csv` (row-aligned labels), `playbook.md` (the resolution
playbook, canonical retrieval source; original PDF alongside).

## Benchmarks

`scripts/load_test.py` against `POST /process/SHP-003` (full pipeline per
request: triage, resolution, communication drafting, SQLite write) on a single
uvicorn worker, rules path, M-series MacBook:

| concurrency | requests | RPS | P50 | P95 | P99 | errors |
|---|---|---|---|---|---|---|
| 20 | 1000 | 676 | 16 ms | 89 ms | 145 ms | 0 |

## Deploy

Render: New -> Blueprint -> pick this repo -> Apply (render.yaml builds from
requirements-api.txt and starts uvicorn). Set DEEPSEEK_API_KEY in the service
environment to enable the LLM path. Dashboard: share.streamlit.io -> Create
app -> main file dashboard.py -> add EXCEPTION_API = "https://<render-url>"
in Secrets.

## Known limits

The LLM path needs a `DEEPSEEK_API_KEY`; until one is set the service runs
rules-only and `/health` says so. Case storage is single-node SQLite; a
multi-worker deployment needs Postgres and a shared cache (Redis) behind the
same interfaces. Notifications are drafted but not sent; an SMS/email gateway
integration is the natural next step. The dataset is small by design; the
generator script exists to stress volume, but real-world log variety will
need prompt and rule tuning against production samples.

## v2: cascade, queue, shared cache, judge, review

**Three-tier model cascade.** Tier 0 is the rule engine: cases with zero
ambiguity signals (clear damage terms, parseable delays, known status codes)
never touch a model. Ambiguous cases go to deepseek-chat with playbook context
and must return a confidence figure. The large model (deepseek-reasoner) is
consulted only when the small model's confidence is below the configured
threshold, or when it disagrees with the rules baseline on a high-stakes case
(VIP/Premium or an already-triggered escalation). Token usage is read from
each response and priced per model, so /metrics reports real spend:
by_model_tier, total_llm_cost_usd, and cost_per_1000_exceptions_usd.

**Queue and workers.** app/queuing.py gives the pipeline an event-queue front:
in-memory by default, Redis Streams (consumer group) when REDIS_URL is set.
Case ids are uuid5 hashes of the event key, so redelivered events are skipped,
not double-processed. scripts/run_workers.py benchmarks the pool; on a
laptop, 8 workers drain 5,200 enqueued events (200 of them deliberate
redeliveries) into exactly 5,000 unique cases at ~935 events/s on the rules
path.

**Shared cache.** With REDIS_URL set, the LLM response cache moves from
per-process LRU to Redis with TTL, so all workers share hits. docker-compose
up starts redis plus the API wired together.

**LLM-as-judge.** POST /evaluate/judge samples processed cases and has the
large model grade each decision's grounding and coherence 1-5, extending
quality measurement beyond the 13 labeled rows. Gated on the API key; 503
with a reason when unavailable.

**Supervisor review.** Escalated cases land as pending_review. POST
/cases/{id}/approve and /cases/{id}/override close the loop, and the
dashboard's case-detail page carries the buttons. Overrides are appended to
the decision's audit trail, which doubles as free labeled data for tuning
the cascade thresholds later.

## Live numbers (real DeepSeek calls, 2026-08-30)

Three ambiguous cases pushed through the cascade with a funded API key:

- Weather-delayed perishable, no duration stated: small model consulted,
  disagreed with the rules baseline on a high-stakes case, escalated to
  deepseek-reasoner, which agreed with the rules (REPLACE, escalate).
  Confidence 0.95, $0.0021, 8.9s.
- Oddly described VIP fragile damage: small model reasoned it out alone
  (audible shifting -> moderate for fragile -> REPLACE), confidence 0.9,
  $0.0008, 5.8s. The customer email it drafted passed validation first try.
- Repeat of the first case: cache hit, $0, 2ms.

Cost per 1,000 exceptions came to $0.95 on this all-ambiguous sample; in the
synthetic worker bench the realistic mix is dominated by rules-tier cases at
zero model cost. The judge (deepseek-reasoner) scored both live decisions
5/5 with grounded rationales.
