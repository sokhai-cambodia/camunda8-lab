# Camunda 8 Lab — Order Fulfillment Demo

Hands-on Camunda 8 environment + a runnable example, built to get you demo-confident in
1-2 hours. Follow the blocks in order — each one is a checkpoint, not just reading material.

Stack: Docker Compose (self-managed, Camunda 8.9.13, H2 storage — no Elasticsearch needed) +
a Python job worker (`pyzeebe`) + the built-in REST and Webhook Connectors + a DMN decision
table + a Camunda Form + a Python service and a Node service. Between the BPMN model and this
README, the lab now touches every Camunda 8 modeling/runtime concept that doesn't require
standing up Elasticsearch or Keycloak (Optimize, Identity, and Web Modeler are out of scope
for that reason).

```
bpmn/             order-fulfillment.bpmn — the executable process
dmn/              stock-check.dmn — the in-stock decision table (business rule task)
forms/            confirm-delivery.form — the Camunda Form shown in Tasklist
docker-compose/   Camunda stack: orchestration (Zeebe+Operate+Tasklist) + connectors
workers/          order_workers.py — job workers (reserve-item, validate-order, handle-payment-failure,
                  ship-order, escalate-to-manager, cancel-order, notify-backorder)
services_python/  order_service.py — FastAPI, triggers/cancels instances via the Zeebe client
services_node/    payment_service.js — Express, called by the Charge Payment connector
slides/           demo-slides.html + camunda8-demo.pptx
requirements.txt  shared venv for workers/ and services_python/
```

`workers/` is only for code that polls Zeebe as a job worker. `services_python/` and
`services_node/` are plain HTTP services that happen to be involved in the process — one
triggers/cancels it, one gets called by a connector — but neither speaks the Zeebe protocol
directly, and neither has to be the same language. `services_node/` exists specifically to
prove that: the connector that calls it doesn't know or care that it's Node instead of Python.

## Architecture & Lifecycle

Read this before Block 1 if you want the big picture first, or after Block 6 if you'd
rather run the demo before reading how it works underneath.

### Architecture — what's running, and who talks to whom

Five independent processes, three languages, two protocols. None of them know about each
other's internals — only the contracts (job types, HTTP routes, message names).

| Process | Language | Port | Talks to Zeebe via | Role |
|---|---|---|---|---|
| `orchestration` container | Java (Zeebe) | `26500` gRPC, `8080` REST/UI | — | The engine itself, plus Operate and Tasklist |
| `connectors` container | Java | `8086` | gRPC (built-in worker) | Executes outbound connector calls; hosts inbound webhooks |
| `services_python/order_service.py` | Python (FastAPI) | `8000` | gRPC (`pyzeebe` client) | Deploys resources; starts/cancels instances |
| `workers/order_workers.py` | Python (`pyzeebe`) | — (long-polls, no server) | gRPC (job worker) | Executes every task type *except* the connector-backed ones |
| `services_node/payment_service.js` | Node (Express) | `8001` | never — plain HTTP only | Called by the outbound connector; doesn't know Camunda exists |

Three ways a BPMN task actually gets executed — this is the thing worth being able to draw
on a whiteboard:

```
Job worker:          BPMN task --(gRPC: poll, activate, complete)--> order_workers.py

Outbound connector:  BPMN task --(gRPC job, picked up by connectors container)-->
                      connectors container --(plain HTTP)--> payment_service.js

Inbound connector:   external caller --(HTTP POST)--> connectors container
                      --(publishes a correlated message)--> BPMN boundary/catch event
```

### Lifecycle — one order, start to finish

**Startup, once, in any order:**
1. `docker compose up -d` — Zeebe + Operate + Tasklist + Connectors come up.
2. `order_workers.py` opens a gRPC connection and starts **long-polling**: "give me jobs of
   type X." Nothing is registered anywhere in advance — it just keeps asking.
3. `payment_service.js` starts as a plain HTTP server. It has no idea Camunda exists.
4. `order_service.py` starts and **deploys** the BPMN + DMN + form as one versioned bundle
   into Zeebe. This defines the process (like registering a class) — no instances exist yet.

**Per order, every time `POST /orders` runs:**
1. `order_service.py` asks Zeebe to create an instance. The token starts, moves to
   **Reserve Items**.
2. Reserve Items is multi-instance — Zeebe creates one **job** per line item (type
   `reserve-item`) and parks them in an internal queue.
3. `order_workers.py`'s poll loop notices the waiting jobs, activates, runs the Python
   function, completes each one. Same poll → run → complete cycle happens later for
   `validate-order`.
4. Token reaches **Determine Stock Status** — a business rule task, so Zeebe evaluates the
   DMN table **internally**. No worker involved at all.
5. Gateway reads `inStock`, routes.
6. **Charge Payment** creates a job of type `io.camunda:http-json:1`. `order_workers.py`
   never sees this one — the **connectors container** picks it up instead, makes the actual
   HTTP call to `payment_service.js:8001`, and completes the job with the response mapped
   into variables. If the response is HTTP 402, the connector throws a BPMN error instead of
   completing normally, and Zeebe routes to the matching boundary error event.
7. **Confirm Delivery** is a *user task*, not a service task — nobody polls for it. Zeebe
   just creates it and waits. At the same moment it starts a **timer** (1 min) and opens a
   **message subscription** (`order-canceled`, correlated by `orderId`). All three —
   a human completing it, the timer, the message — race each other; whichever happens first
   wins and interrupts the other two.
8. A cancel arrives as: `curl .../cancel` → `order_service.py` → HTTP POST to the connectors
   container's webhook → connectors container publishes a correlated message into Zeebe →
   Zeebe matches it to the waiting subscription → interrupts the user task.

That race in step 7 is the single most useful thing to be able to explain unprompted — it's
the moment that makes boundary events click for people who've only seen linear flowcharts.

## Block 1 — Concepts (10 min)

- **BPMN** — the diagram *is* the executable process. No separate "translate design to code" step.
- **Zeebe** — the workflow engine at the core. Horizontally scalable, event-sourced. Talks gRPC on `:26500`.
- **Job workers** — external processes that poll Zeebe for work of a given `task type`, do the work, report back. This is how Camunda 8 stays polyglot — workers can be Python, Java, Node, anything with a gRPC/REST client.
- **Connectors** — prebuilt workers Camunda ships for you, configured on the BPMN task instead of hand-written. We use two kinds: an **outbound** REST connector ("Charge Payment" calls out to a service) and an **inbound** Webhook connector ("Order Canceled" is triggered by an incoming HTTP call).
- **DMN** — decision tables modeled separately from the process flow. A **business rule task** calls one the same way a service task calls a job worker; ours picks in-stock vs. out-of-stock.
- **Forms** — a JSON schema attached to a user task that Tasklist renders automatically, instead of a bare "complete this task" button.
- **Boundary events** — attached to the edge of a task, they race the task itself. A **timer** boundary times out a task; an **error** boundary catches a business failure thrown by a connector/worker; a **message** boundary waits for an external event. All three interrupt "Confirm Delivery" or "Charge Payment" in this model.
- **Multi-instance** — runs one activity per element of a collection (our "Reserve Items" step, once per line item) instead of once per process instance.
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

Flow: **Order Received** → *Reserve Items* (multi-instance job worker, one per line item) →
*Validate Order* (job worker) → *Determine Stock Status* (business rule task → DMN) →
**In Stock?** gateway →
- Yes → *Charge Payment* (REST connector)
  - normal → *Ship Order* (job worker) → *Confirm Delivery* (user task + Camunda Form, assigned to `demo`)
    - completed → **Order Completed**
    - timer boundary (1 min) → *Escalate to Manager* → **Order Escalated**
    - message boundary (webhook) → *Cancel Order* → **Order Canceled**
  - error boundary (payment declined) → *Handle Payment Failure* → **Order Payment Failed**
- No → *Notify Backorder* (job worker) → **Order Backordered**

Talking points:
- The gateway condition (`inStock = true`) reads a process variable that the *Determine Stock Status* business rule task set by calling `dmn/stock-check.dmn` — open that decision table in Modeler to show the same logic as a table instead of code.
- Click "Charge Payment" and open its properties panel — it has no custom code behind it, just a configured URL/method/body, plus an `errorExpression` header that turns an HTTP 402 into a BPMN error for the boundary event attached to it. Contrast this with "Ship Order," which is a real job worker in `workers/order_workers.py`.
- Click "Confirm Delivery" — its Form tab shows `forms/confirm-delivery.form`, and it has three ways out: complete it, let the timer boundary fire, or hit it with the cancel webhook. Same task, three different exits.
- "Reserve Items" has the multi-instance marker (three vertical bars) in its bottom-left corner — click it and open the "Multi-instance" tab to see `items` as the input collection.

## Block 4 — Run the workers and services (25 min)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python workers/order_workers.py
```

Leave this running in its own terminal — it's polling Zeebe for `reserve-item`,
`validate-order`, `handle-payment-failure`, `ship-order`, `escalate-to-manager`,
`cancel-order`, and `notify-backorder` jobs. Note `charge-payment` is deliberately *not*
here — that job type doesn't exist anymore; the BPMN task now uses the connector directly.

In a **second** terminal, start the microservice the Connector calls into — this one's
Node, not Python, deliberately (see Block 1's polyglot point):
```powershell
cd services_node
npm install
npm start
```
`payment_service.js` has zero imports from anything Camunda/Zeebe-related — it's a normal
Express endpoint that has no idea Camunda exists. The REST connector calls it over plain
HTTP on port 8001, same as it would call any existing internal API in any language.

In a **third** terminal, start the service that triggers instances:
```powershell
.venv\Scripts\Activate.ps1
uvicorn services_python.order_service:app --port 8000
```
On startup this deploys the BPMN, DMN, and form resources once and exposes `POST /orders`
plus `POST /orders/{order_id}/cancel`. Open http://localhost:8000/docs for the interactive
Swagger UI — good for the demo, since you can trigger (and cancel) orders by clicking
"Try it out" instead of typing curl live.

## Block 5 — Run it end to end (15 min)

Start the happy path (`quantity=5`, ≤10 → in stock):
```powershell
curl -X POST http://localhost:8000/orders -H "Content-Type: application/json" -d "{\"order_id\":\"ORD-1001\",\"quantity\":5}"
```
1. Watch the worker terminal (job side) and the payment service terminal (connector side) both log activity — including the `reserve-item` log line running once per entry in `items`.
2. Open Operate → click the running instance → watch tokens move through the diagram live.
3. Open Tasklist → find the "Confirm Delivery" task assigned to `demo` → you'll see the real form (delivery notes + a satisfaction checkbox) instead of a blank task → fill it in and complete it.
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

## Block 7 — Three more branches: decline, cancel, escalate (15 min)

Each of these ends the instance a different way than the happy path — good for showing
that "the process" isn't just one line through the diagram.

**Payment declined (error boundary event).** `quantity=10` is a deliberate trigger in
`payment_service.js` that returns HTTP 402 — chosen because it's still the top of the
DMN's in-stock range, so it reaches Charge Payment instead of being backordered first:
```powershell
curl -X POST http://localhost:8000/orders -H "Content-Type: application/json" -d "{\"order_id\":\"ORD-2001\",\"quantity\":10}"
```
The REST connector's `errorExpression` turns that into a BPMN error; the boundary error
event on "Charge Payment" catches it and routes to `handle-payment-failure` instead of
"Ship Order". In Operate, this instance ends at **Order Payment Failed** — no incident,
because the error was *handled*, not unhandled like Block 6's.

**Cancel via webhook (message boundary event + inbound connector).** Start an order, then
before completing "Confirm Delivery" in Tasklist, cancel it:
```powershell
curl -X POST http://localhost:8000/orders -H "Content-Type: application/json" -d "{\"order_id\":\"ORD-2002\",\"quantity\":5}"
curl -X POST http://localhost:8000/orders/ORD-2002/cancel
```
`/cancel` POSTs to the connectors container's inbound Webhook endpoint
(`http://localhost:8086/inbound/order-canceled`), which correlates by `orderId` to the
message boundary event on "Confirm Delivery" and routes to `cancel-order`. Ends at
**Order Canceled**. Talking point: this is the same mechanism a real system (e.g. a
customer portal calling a webhook) would use to interrupt a running process from outside.

**Timeout (timer boundary event).** Start another order and just leave "Confirm Delivery"
sitting in Tasklist without completing it for about a minute — the timer boundary fires on
its own, runs `escalate-to-manager`, and the instance ends at **Order Escalated**. No curl
needed for this one; it's the passage of time itself that's the trigger.

## Block 8 — Slides

See `slides/` — an HTML deck you can open in a browser (`slides/demo-slides.html`) and
present directly, or use as the outline for your own deck.

## Block 9 — Dry run (10 min)

Run the full sequence solo, end to end, before the real demo: stack up → deploy → happy
path → backorder path → incident → retry → decline → cancel → escalate. Time yourself. If
Docker startup is slow, start `docker compose up -d` a few minutes before your actual demo
slot.

## Shutting down

```powershell
cd docker-compose
docker compose down -v   # -v also wipes the H2 data volume
```
