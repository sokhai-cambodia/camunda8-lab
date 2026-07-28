import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel
from pyzeebe import ZeebeClient, create_insecure_channel

BPMN_PATH = Path(__file__).resolve().parent.parent / "bpmn" / "order-fulfillment.bpmn"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order-api")

state: dict[str, ZeebeClient] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Channel/client must be created inside the running event loop (uvicorn's),
    # same reasoning as order_workers.py: pyzeebe's grpc streams bind to
    # whatever loop is running when they're created.
    channel = create_insecure_channel(grpc_address="localhost:26500")
    client = ZeebeClient(channel)
    logger.info("Deploying %s ...", BPMN_PATH.name)
    await client.deploy_resource(str(BPMN_PATH))
    state["client"] = client
    yield
    state.clear()


app = FastAPI(title="Order Fulfillment API", lifespan=lifespan)


class OrderRequest(BaseModel):
    order_id: str
    item: str = "Wireless Mouse"
    quantity: int


class OrderResponse(BaseModel):
    order_id: str
    process_instance_key: int


@app.post("/orders", response_model=OrderResponse, status_code=201)
async def start_order(order: OrderRequest) -> OrderResponse:
    variables = {"orderId": order.order_id, "item": order.item, "quantity": order.quantity}
    logger.info("Starting order-fulfillment instance: %s", variables)
    response = await state["client"].run_process(
        bpmn_process_id="order-fulfillment-process", variables=variables
    )
    return OrderResponse(order_id=order.order_id, process_instance_key=response.process_instance_key)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
