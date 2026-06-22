"""One-time setup: create the ACA sandbox group and grant data-plane access.

Adapted from the ACA Sandboxes Python SDK quickstart. Run this once to:
  1. ensure the resource group exists,
  2. create the sandbox group used for per-session isolation, and
  3. grant a principal the "Container Apps SandboxGroup Data Owner" role so it
     can create/exec/delete sandboxes.

Usage (grant the Container App's managed identity, output by Bicep):
    python scripts/setup_sandbox.py --principal-id <PRINCIPAL_ID> --principal-type ServicePrincipal

Usage (grant yourself for local dev):
    python scripts/setup_sandbox.py --principal-id $(az ad signed-in-user --query id -o tsv) --principal-type User

Reads AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_SANDBOX_GROUP, AZURE_REGION
from the environment (or a local .env).
"""
from __future__ import annotations

import argparse
import os
import uuid

from azure.identity import DefaultAzureCredential
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.containerapps.sandbox import SandboxGroupManagementClient

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Built-in role: Container Apps SandboxGroup Data Owner.
ROLE_DEF_ID = "c24cf47c-5077-412d-a19c-45202126392c"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal-id", required=True, help="Object id of the identity to grant access.")
    parser.add_argument(
        "--principal-type",
        default="ServicePrincipal",
        choices=["ServicePrincipal", "User", "Group"],
        help="Type of the principal being granted access.",
    )
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    sub = os.environ["AZURE_SUBSCRIPTION_ID"]
    rg = os.environ["AZURE_RESOURCE_GROUP"]
    group = os.environ["AZURE_SANDBOX_GROUP"]
    region = os.environ.get("AZURE_REGION", "eastus2")

    ResourceManagementClient(credential, sub).resource_groups.create_or_update(
        rg, {"location": region}
    )

    SandboxGroupManagementClient(
        credential, subscription_id=sub, resource_group=rg
    ).create_group(group, location=region)

    scope = (
        f"/subscriptions/{sub}/resourceGroups/{rg}"
        f"/providers/Microsoft.App/sandboxGroups/{group}"
    )
    AuthorizationManagementClient(credential, sub).role_assignments.create(
        scope=scope,
        role_assignment_name=str(uuid.uuid4()),
        parameters={
            "properties": {
                "roleDefinitionId": f"/subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions/{ROLE_DEF_ID}",
                "principalId": args.principal_id,
                "principalType": args.principal_type,
            }
        },
    )

    print(f"Setup complete: rg={rg}, sandbox_group={group}, role granted to {args.principal_id}.")
    print("Role assignments take 30-60 seconds to propagate.")


if __name__ == "__main__":
    main()
