import logging
import random

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("payment-service")

# Stand-in for a real payment microservice. Camunda knows nothing about this
# service directly -- the charge-payment job worker in order_workers.py calls
# it over plain HTTP, same as it would call any existing internal API.
app = FastAPI(title="Payment Service")


class ChargeRequest(BaseModel):
    order_id: str
    quantity: int


class ChargeResponse(BaseModel):
    payment_id: str
    amount_charged: float


@app.post("/charge", response_model=ChargeResponse)
async def charge(request: ChargeRequest) -> ChargeResponse:
    if request.quantity == 10:
        # Deliberate demo trigger: quantity=10 is the top of the DMN's in-stock
        # range (dmn/stock-check.dmn), so it still reaches Charge Payment before
        # declining here -- caught by the BPMN error boundary event via
        # errorExpression. Shows stock-check and payment authorization are
        # independent concerns: being in stock doesn't guarantee funds clear.
        logger.info("Declined order %s: insufficient funds", request.order_id)
        raise HTTPException(status_code=402, detail={"error": "insufficient_funds"})

    amount = round(request.quantity * 19.99, 2)
    payment_id = f"PMT-{random.randint(10000, 99999)}"
    logger.info("Charged order %s: $%.2f (%s)", request.order_id, amount, payment_id)
    return ChargeResponse(payment_id=payment_id, amount_charged=amount)
