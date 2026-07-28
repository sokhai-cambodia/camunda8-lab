# Camunda 8 Lab — Order Fulfillment Demo

Hands-on Camunda 8 environment + a runnable example, built to get you demo-confident in
1-2 hours. Follow the blocks in order — each one is a checkpoint, not just reading material.

Stack: Docker Compose (self-managed, Camunda 8.9.13, H2 storage — no Elasticsearch needed) +
Python job workers (`pyzeebe`).

## Block 1 — Concepts (10 min)

- **BPMN** — the diagram *is* the executable process. No separate "translate design to code" step.
- **Zeebe** — the workflow engine at the core. Horizontally scalable, event-sourced. Talks gRPC on `:26500`.
- **Job workers** — external processes that poll Zeebe for work of a given `task type` (e.g. `charge-payment`), do the work, report back. This is how Camunda 8 stays polyglot — workers can be Python, Java, Node, anything with a gRPC/REST client.
- **Operate** — web UI to monitor running/completed process instances and fix **incidents** (failed jobs).
- **Tasklist** — web UI for humans to complete **user tasks** (the manual steps in a process).
- **Connectors** (not used in this demo, worth mentioning in slides) — prebuilt workers for common systems (REST, Slack, email, etc.) so you don't hand-write a worker for everything.

**One-liner for the demo audience:** "BPMN defines *what* should happen and in what order; job workers define *how* each step actually gets done; Zeebe guarantees the process moves forward correctly even across crashes, retries, and scale."

## Block 2 — Start the stack (15 min)

```powershell
cd docker-compose
docker compose up -d
```

First run pulls the `camunda/camunda:8.9.13` image (~1GB) — kick this off first and read Block 1/3 while it pulls.

Check health:
```powershell
docker compose ps
docker compose logs -f orchestration   # wait for "Broker is ready"
```

Once ready, open:
- Operate: http://localhost:8080/operate (login `demo` / `demo`)
- Tasklist: http://localhost:8080/tasklist (same login)

## Block 3 — The model (15 min)

Open `bpmn/order-fulfillment.bpmn` in [Camunda Desktop Modeler](https://camunda.com/download/modeler/) or drag it into https://modeler.camunda.io to see it visually (good for a slide screenshot).

Flow: **Order Received** → *Validate Order* (service task) → **In Stock?** gateway →
- Yes → *Charge Payment* → *Ship Order* → *Confirm Delivery* (user task, assigned to `demo`) → **Order Completed**
- No → *Notify Backorder* → **Order Backordered**

Talking point: point out that the gateway condition (`inStock = true`) reads a process
variable that a job worker set — this is the live link between BPMN and code.

## Block 4 — Run the workers (25 min)

```powershell
cd workers
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python order_workers.py
```

Leave this running in its own terminal — it's polling Zeebe for `validate-order`,
`charge-payment`, `ship-order`, `notify-backorder` jobs. Read through `order_workers.py`
while it starts: notice each `@worker.task(task_type=...)` maps 1:1 to a service task's
`zeebe:taskDefinition type` in the BPMN file.

## Block 5 — Run it end to end (15 min)

In a **second** terminal (keep workers running):
```powershell
cd workers
.venv\Scripts\Activate.ps1
python start_order.py ORD-1001 5
```

This deploys the BPMN file and starts an instance with `quantity=5` (≤10 → in stock →
happy path). Now:
1. Watch the worker terminal log each step.
2. Open Operate → click the running instance → watch tokens move through the diagram live.
3. Open Tasklist → find the "Confirm Delivery" task assigned to `demo` → complete it.
4. Back in Operate, the instance shows as completed.

Try the backorder path too:
```powershell
python start_order.py ORD-1002 15
```
`quantity=15` > 10 → gateway routes to *Notify Backorder* instead.

## Block 6 — Failure demo (10 min)

This is the part that actually impresses a technical audience: show what happens when
something breaks.

```powershell
python start_order.py ORD-1003 0
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
