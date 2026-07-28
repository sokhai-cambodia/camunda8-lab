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

    @worker.task(task_type="validate-order")
    def validate_order(orderId: str, item: str, quantity: int) -> dict:
        if quantity <= 0:
            # Left unhandled on purpose: Zeebe raises an incident for this job,
            # which is what we use to demo Operate's incident view + retry.
            raise ValueError(f"Invalid quantity {quantity} for order {orderId}")

        in_stock = quantity <= 10
        logger.info("Validated order %s (%s x%s) -> inStock=%s", orderId, item, quantity, in_stock)
        return {"inStock": in_stock}

    # No "charge-payment" job worker here -- that step is now handled by the
    # built-in REST connector configured directly on the BPMN task, which
    # calls services/payment_service.py without any custom polling code.

    @worker.task(task_type="ship-order", exception_handler=on_error)
    def ship_order(orderId: str) -> dict:
        tracking_number = f"TRK-{random.randint(100000, 999999)}"
        logger.info("Shipped order %s -> %s", orderId, tracking_number)
        return {"trackingNumber": tracking_number}

    @worker.task(task_type="notify-backorder", exception_handler=on_error)
    def notify_backorder(orderId: str, item: str) -> dict:
        logger.info("Notified customer: order %s (%s) is backordered", orderId, item)
        return {"backorderNotified": True}

    logger.info("Starting order workers, connecting to localhost:26500 ...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
