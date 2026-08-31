# Delivery Exception Handler

An AI system that handles failed package deliveries the way a good operations
team would, in milliseconds instead of half an hour.

## The problem

Roughly 1 in 10 packages doesn't make it on the first try. Nobody home, wrong
address, crushed box, customer refuses it, a snowstorm sits on the route.
Every failed delivery costs another truck roll, and the hidden cost is worse:
after 2 or 3 bad deliveries, customers simply stop ordering. Logistics
companies keep whole teams reading messy driver notes ("cant find building
999 asked around nobody knows it") and deciding, case by case, what to do
next. Policy says each case should be resolved within 30 minutes. Humans get
tired, skip steps, and apply the rulebook inconsistently.

## What this system does

Point it at the raw courier scan feed and it does the whole job:

- Reads the messy driver notes and figures out what actually happened,
  ignoring duplicate scans and routine noise.
- Decides what to do next, exactly by the company playbook: reschedule,
  reroute to a pickup locker, replace the item, or send it back.
- Knows when a human must step in, and says why: a third failed attempt, a
  VIP customer having a bad month, a spoiled food package, an address that
  looks like fraud.
- Writes the message the customer receives, in the right channel and tone: a
  formal email with an apology and a service credit for a VIP, a short
  friendly text for everyone else.
- Shows its work. Every decision comes with its reasoning, the playbook
  section it relied on, and a live dashboard for the operations team.
- Keeps humans in charge. Escalated cases wait for a supervisor, who can
  approve or override the decision with one click; overrides are logged.

On the labeled test scenarios it gets everything right: the right resolution,
the right escalation call, the right tone, 100% across the board. Under load
it answers in well under a tenth of a second. If the AI model is unreachable,
or someone hides instructions inside a driver note to trick it, it falls back
to the rulebook and keeps going. It does not guess, and it does not go down.

## The LLM stack

- A three-tier model cascade: clear cases are decided by rules for free,
  ambiguous ones go to a small model (deepseek-chat), and only uncertain
  high-stakes cases reach the large reasoning model (deepseek-reasoner). The
  dashboard shows the spend as cost per 1,000 exceptions
- Retrieval over the company's operations playbook, so decisions are grounded
  in policy rather than model memory
- A multi-agent pipeline: one agent triages the log stream, one decides the
  resolution, one writes the customer message, and a critic checks the result
  before it ships
- Guardrails with teeth: the model proposes, hard business rules make the
  final call, and every disagreement is recorded
- Prompt-injection screening on all free-text input
- Response caching, so repeated cases cost nothing and return instantly
- An evaluation harness that scores the pipeline against human-labeled ground
  truth, so any prompt or model change is measurable

Built with Python, FastAPI, SQLite and Streamlit. Tested in CI on every
change, ships with a Dockerfile. Engineering details, benchmarks and deploy
notes: [docs/TECHNICAL.md](docs/TECHNICAL.md).

## Try it

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python main.py                          # API on :8010
./venv/bin/python -m streamlit run dashboard.py    # dashboard
```

Open the dashboard, click "Process all delivery logs", and watch it work
through the sample day: 13 scan events, 9 real exceptions, 7 escalations,
every customer message ready to send. An API key (`DEEPSEEK_API_KEY`) turns
on the AI model; without one the system runs on the rulebook alone.
