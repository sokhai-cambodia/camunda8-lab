import asyncio
import sys
from pathlib import Path

from pyzeebe import ZeebeClient, create_insecure_channel

BPMN_PATH = Path(__file__).resolve().parent.parent / "bpmn" / "order-fulfillment.bpmn"


async def main() -> None:
    channel = create_insecure_channel(grpc_address="localhost:26500")
    client = ZeebeClient(channel)

    print(f"Deploying {BPMN_PATH.name} ...")
    await client.deploy_resource(str(BPMN_PATH))

    order_id = sys.argv[1] if len(sys.argv) > 1 else "ORD-1001"
    quantity = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    variables = {"orderId": order_id, "item": "Wireless Mouse", "quantity": quantity}
    print(f"Starting process instance with variables: {variables}")
    process_instance_key = await client.run_process(
        bpmn_process_id="order-fulfillment-process", variables=variables
    )
    print(f"Started process instance: {process_instance_key}")
    print("Watch it in Operate: http://localhost:8080/operate (login demo/demo)")
    print("Complete the user task in Tasklist: http://localhost:8080/tasklist")


if __name__ == "__main__":
    asyncio.run(main())
