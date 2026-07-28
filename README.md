# Camunda 8 Lab — Order Fulfillment Demo

Hands-on Camunda 8 environment + a runnable example, built to get you demo-confident in
1-2 hours. Follow the blocks in order — each one is a checkpoint, not just reading material.

Stack: Docker Compose (self-managed, Camunda 8.9.13, H2 storage — no Elasticsearch needed) +
a Python job worker (`pyzeebe`) + the built-in REST Connector + two small FastAPI services.

```
bpmn/            order-fulfillment.bpmn — the executable process
docker-compose/  Camunda stack: orchestration (Zeebe+Operate+Tasklist) + connectors
workers/         order_workers.py — the one real Zeebe job worker (ship-order, notify-backorder, validate-order)
services/        order_service.py (triggers instances) + payment_service.py (plain microservice, called by the Connector)
slides/          demo-slides.html
requirements.txt shared venv for workers/ and services/
```

`workers/` is only for code that polls Zeebe as a job worker. `services/` is plain FastAPI
apps that happen to be involved in the process — one triggers it, one gets called by a
Connector — but neither of them speaks the Zeebe protocol directly.

## Block 1 — Concepts (10 min)

- **BPMN** — the diagram *is* the executable process. No separate "translate design to code" step.
- **Zeebe** — the workflow engine at the core. Horizontally scalable, event-sourced. Talks gRPC on `:26500`.
- **Job workers** — external processes that poll Zeebe for work of a given `task type`, do the work, report back. This is how Camunda 8 stays polyglot — workers can be Python, Java, Node, anything with a gRPC/REST client.
- **Connectors** — prebuilt workers Camunda ships for you (REST, Slack, email, etc.), configured on the BPMN task itself instead of hand-written. Our "Charge Payment" step uses the built-in REST connector.
- **Operate** — web UI to monitor running/completed process instances and fix **incidents** (failed jobs).
- **Tasklist** — web UI for humans to complete **user tasks** (the manual steps in a process).

**One-liner for the demo audience:** "BPMN defines *what* should happen and in what order; job workers and connectors define *how* each step actually gets done; Zeebe guarantees the process moves forward correctly even across crashes, retries, and scale."

## Block 2 — Start the stack (15 min)

```powershell
cd docker-compose
docker compose up -d
```

First run pulls the `camunda/camunda:8.9.13` and `camunda/connectors-bundle:8.9.6` images
(~1.2GB total) — kick this off first and read Block 1/3 while it pulls.

Check health:
```powershell
docker compose ps
docker compose logs -f orchestration   # wait for "Broker is ready"
```

Once ready, open:
- Operate: http://localhost:8080/operate (login `demo` / `demo`)
- Tasklist: http://localhost:8080/tasklist (same login)

## Block 3 — The model (15 min)

Open `bpmn/order-fulfillment.bpmn` in [Camunda Desktop Modeler](https://camunda.com/download/modeler/)
or drag it into https://demo.bpmn.io to see it visually (good for a slide screenshot).

Flow: **Order Received** → *Validate Order* (job worker) → **In Stock?** gateway →
- Yes → *Charge Payment* (REST connector) → *Ship Order* (job worker) → *Confirm Delivery* (user task, assigned to `demo`) → **Order Completed**
- No → *Notify Backorder* (job worker) → **Order Backordered**

Talking points:
- The gateway condition (`inStock = true`) reads a process variable that `validate_order` set — the live link between BPMN and code.
- Click "Charge Payment" and open its properties panel — it has no custom code behind it, just a configured URL/method/body. Contrast this with "Ship Order," which is a real job worker in `workers/order_workers.py`.

## Block 4 — Run the workers and services (25 min)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python workers/order_workers.py
```

Leave this running in its own terminal — it's polling Zeebe for `validate-order`,
`ship-order`, and `notify-backorder` jobs. Note `charge-payment` is deliberately *not*
here — that job type doesn't exist anymore; the BPMN task now uses the connector directly.

In a **second** terminal, start the microservice the Connector calls into:
```powershell
.venv\Scripts\Activate.ps1
uvicorn services.payment_service:app --port 8001
```
`payment_service.py` has zero imports from `pyzeebe` — it's a normal REST endpoint that
has no idea Camunda exists.

In a **third** terminal, start the service that triggers instances:
```powershell
.venv\Scripts\Activate.ps1
uvicorn services.order_service:app --port 8000
```
On startup this deploys the BPMN file once and exposes `POST /orders`. Open
http://localhost:8000/docs for the interactive Swagger UI — good for the demo, since you
can trigger orders by clicking "Try it out" instead of typing curl live.

## Block 5 — Run it end to end (15 min)

Start the happy path (`quantity=5`, ≤10 → in stock):
```powershell
curl -X POST http://localhost:8000/orders -H "Content-Type: application/json" -d "{\"order_id\":\"ORD-1001\",\"quantity\":5}"
```
1. Watch the worker terminal (job side) and the payment service terminal (connector side) both log activity.
2. Open Operate → click the running instance → watch tokens move through the diagram live.
3. Open Tasklist → find the "Confirm Delivery" task assigned to `demo` → complete it.
4. Back in Operate, the instance shows as completed.

Try the backorder path too:
```powershell
curl -X POST http://localhost:8000/orders -H "Content-Type: application/json" -d "{\"order_id\":\"ORD-1002\",\"quantity\":15}"
```
`quantity=15` > 10 → gateway routes to *Notify Backorder* instead.

## Block 6 — Failure demo (10 min)

This is the part that actually impresses a technical audience: show what happens when
something breaks.

```powershell
curl -X POST http://localhost:8000/orders -H "Content-Type: application/json" -d "{\"order_id\":\"ORD-1003\",\"quantity\":0}"
```

`quantity=0` makes `validate_order` raise an unhandled exception. In Operate:
1. The instance shows a red **incident** badge.
2. Click into it — Operate shows the exact exception message and stack trace.
3. Click the failed variable, edit `quantity` to a valid value (e.g. `5`) directly in Operate.
4. Click **Retry** — the job re-executes and the instance continues normally.

Talking point: no code deploy, no restart, no lost work — you fixed bad data and resumed a
running process from where it failed.

## Block 7 — Slides

See `slides/` — an HTML deck you can open in a browser (`slides/demo-slides.html`) and
present directly, or use as the outline for your own deck.

## Block 8 — Dry run (10 min)

Run the full sequence solo, end to end, before the real demo: stack up → deploy → happy
path → backorder path → incident → retry. Time yourself. If Docker startup is slow, start
`docker compose up -d` a few minutes before your actual demo slot.

## Shutting down

```powershell
cd docker-compose
docker compose down -v   # -v also wipes the H2 data volume
```
