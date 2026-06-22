"""List the currently live sandboxes in the configured sandbox group."""
import os

from dotenv import load_dotenv

load_dotenv()

from azure.identity import DefaultAzureCredential
from azure.containerapps.sandbox import SandboxGroupClient, endpoint_for_region

client = SandboxGroupClient(
    endpoint=endpoint_for_region(os.environ["AZURE_REGION"]),
    subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
    resource_group=os.environ["AZURE_RESOURCE_GROUP"],
    sandbox_group=os.environ["AZURE_SANDBOX_GROUP"],
    credential=DefaultAzureCredential(),
)

sandboxes = list(client.list_sandboxes())
print(f"LIVE SANDBOXES: {len(sandboxes)}")
for s in sandboxes:
    labels = getattr(s, "labels", {}) or {}
    session = labels.get("session", "?")
    print(f" - id={s.id}  session={session}  state={s.state}  created={s.created_at}")
