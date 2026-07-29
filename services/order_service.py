import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from pyzeebe import ZeebeClient, create_insecure_channel

LAB_ROOT = Path(__file__).resolve().parent.parent
BPMN_PATH = LAB_ROOT / "bpmn" / "order-fulfillment.bpmn"
DMN_PATH = LAB_ROOT / "dmn" / "stock-check.dmn"
FORM_PATH = LAB_ROOT / "forms" / "confirm-delivery.form"

# The connectors container's inbound webhook endpoint -- posting here is what
# correlates the "Order Canceled" boundary message event on Confirm Delivery.
CANCEL_WEBHOOK_URL = "http://localhost:8086/inbound/order-canceled"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order-service")

state: dict[str, ZeebeClient] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Channel/client must be created inside the running event loop (uvicorn's),
    # same reasoning as order_workers.py: pyzeebe's grpc streams bind to
    # whatever loop is running when they're created.
    channel = create_insecure_channel(grpc_address="localhost:26500")
    client = ZeebeClient(channel)
    logger.info("Deploying %s, %s, %s ...", BPMN_PATH.name, DMN_PATH.name, FORM_PATH.name)
    await client.deploy_resource(str(BPMN_PATH), str(DMN_PATH), str(FORM_PATH))
    state["client"] = client
    yield
    state.clear()


app = FastAPI(title="Order Fulfillment API", lifespan=lifespan)


class OrderRequest(BaseModel):
    order_id: str
    item: str = "Wireless Mouse"
    items: list[str] = ["Wireless Mouse"]
    quantity: int


class OrderResponse(BaseModel):
    order_id: str
    process_instance_key: int


@app.post("/orders", response_model=OrderResponse, status_code=201)
async def start_order(order: OrderRequest) -> OrderResponse:
    variables = {
        "orderId": order.order_id,
        "item": order.item,
        "items": order.items,
        "quantity": order.quantity,
    }
    logger.info("Starting order-fulfillment instance: %s", variables)
    response = await state["client"].run_process(
        bpmn_process_id="order-fulfillment-process", variables=variables
    )
    return OrderResponse(order_id=order.order_id, process_instance_key=response.process_instance_key)


@app.post("/orders/{order_id}/cancel", status_code=202)
async def cancel_order(order_id: str) -> dict[str, str]:
    # Goes through the same path a real external system would use: an HTTP call
    # into the connectors container's inbound webhook, not a direct Zeebe call.
    logger.info("Requesting cancellation for order %s via webhook", order_id)
    async with httpx.AsyncClient() as http_client:
        await http_client.post(CANCEL_WEBHOOK_URL, json={"orderId": order_id})
    return {"status": "cancellation requested"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
