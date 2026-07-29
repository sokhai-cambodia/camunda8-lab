"""Deploy the BPMN/DMN/form bundle to Zeebe without restarting order_service.

order_service.py starts a process instance by bpmn_process_id (no version
pinned), so Zeebe always runs whichever version was deployed most recently --
run this after editing bpmn/dmn/form files and the running FastAPI service
picks up the change on the next POST /orders, no restart needed.
"""

import asyncio
import logging
from pathlib import Path

from pyzeebe import ZeebeClient, create_insecure_channel

LAB_ROOT = Path(__file__).resolve().parent.parent
BPMN_PATH = LAB_ROOT / "process" / "bpmn" / "order-fulfillment.bpmn"
DMN_PATH = LAB_ROOT / "process" / "dmn" / "stock-check.dmn"
FORM_PATH = LAB_ROOT / "process" / "forms" / "confirm-delivery.form"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("deploy")


async def main() -> None:
    channel = create_insecure_channel(grpc_address="localhost:26500")
    client = ZeebeClient(channel)
    logger.info("Deploying %s, %s, %s ...", BPMN_PATH.name, DMN_PATH.name, FORM_PATH.name)
    response = await client.deploy_resource(str(BPMN_PATH), str(DMN_PATH), str(FORM_PATH))
    for deployment in response.deployments:
        logger.info("Deployed: %s", deployment)


if __name__ == "__main__":
    asyncio.run(main())
