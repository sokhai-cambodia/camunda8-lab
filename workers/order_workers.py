import asyncio
import logging
import random

from pyzeebe import Job, JobController, ZeebeWorker, create_insecure_channel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order-workers")


async def on_error(exception: Exception, job: Job, job_controller: JobController):
    logger.error("Task %s failed: %s", job.type, exception)
    await job_controller.set_error_status(job, f"{job.type} failed: {exception}")


async def main() -> None:
    # Channel/worker must be created inside the running event loop (asyncio.run
    # creates it), otherwise pyzeebe's grpc streams bind to the wrong loop and crash.
    channel = create_insecure_channel(grpc_address="localhost:26500")
    worker = ZeebeWorker(channel)

    @worker.task(task_type="reserve-item", exception_handler=on_error)
    def reserve_item(item: str) -> dict:
        reservation_id = f"RSV-{random.randint(100000, 999999)}"
        logger.info("Reserved item %r -> %s", item, reservation_id)
        return {"reservationId": reservation_id}

    @worker.task(task_type="validate-order")
    def validate_order(orderId: str, item: str, quantity: int) -> None:
        if quantity <= 0:
            # Left unhandled on purpose: Zeebe raises an incident for this job,
            # which is what we use to demo Operate's incident view + retry.
            raise ValueError(f"Invalid quantity {quantity} for order {orderId}")

        logger.info("Validated order %s (%s x%s)", orderId, item, quantity)

    # No "determine-stock" job worker here -- the in-stock decision is now a
    # DMN business rule task (dmn/stock-check.dmn) instead of inline Python.

    # No "charge-payment" job worker here -- that step is now handled by the
    # built-in REST connector configured directly on the BPMN task, which
    # calls services_node/payment_service.js without any custom polling code.

    @worker.task(task_type="handle-payment-failure", exception_handler=on_error)
    def handle_payment_failure(orderId: str) -> dict:
        logger.info("Payment declined for order %s -- notifying customer", orderId)
        return {"paymentFailureHandled": True}

    @worker.task(task_type="ship-order", exception_handler=on_error)
    def ship_order(orderId: str) -> dict:
        tracking_number = f"TRK-{random.randint(100000, 999999)}"
        logger.info("Shipped order %s -> %s", orderId, tracking_number)
        return {"trackingNumber": tracking_number}

    # No "confirm-delivery" job worker -- it's a Camunda Form-backed user task,
    # completed by a human in Tasklist.

    @worker.task(task_type="escalate-to-manager", exception_handler=on_error)
    def escalate_to_manager(orderId: str) -> dict:
        logger.info("Order %s not confirmed in time -- escalating to manager", orderId)
        return {"escalated": True}

    @worker.task(task_type="cancel-order", exception_handler=on_error)
    def cancel_order(orderId: str) -> dict:
        logger.info("Order %s canceled via webhook", orderId)
        return {"canceled": True}

    @worker.task(task_type="notify-backorder", exception_handler=on_error)
    def notify_backorder(orderId: str, item: str) -> dict:
        logger.info("Notified customer: order %s (%s) is backordered", orderId, item)
        return {"backorderNotified": True}

    logger.info("Starting order workers, connecting to localhost:26500 ...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
