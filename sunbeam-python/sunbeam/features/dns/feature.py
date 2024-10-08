# Copyright (c) 2023 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging

import click
from packaging.version import Version
from rich.console import Console

from sunbeam.clusterd.service import ClusterServiceUnavailableException
from sunbeam.core.common import BaseStep, run_plan
from sunbeam.core.deployment import Deployment
from sunbeam.core.juju import JujuHelper, run_sync
from sunbeam.core.manifest import AddManifestStep, CharmManifest, SoftwareConfig
from sunbeam.core.openstack import OPENSTACK_MODEL
from sunbeam.core.steps import PatchLoadBalancerServicesStep
from sunbeam.core.terraform import TerraformInitStep
from sunbeam.features.interface.v1.openstack import (
    ApplicationChannelData,
    EnableOpenStackApplicationStep,
    OpenStackControlPlaneFeature,
    TerraformPlanLocation,
)
from sunbeam.utils import argument_with_deprecated_option
from sunbeam.versions import BIND_CHANNEL, OPENSTACK_CHANNEL

LOG = logging.getLogger(__name__)
console = Console()


class PatchBindLoadBalancerStep(PatchLoadBalancerServicesStep):
    def services(self) -> list[str]:
        """List of services to patch."""
        return ["bind"]

    def model(self) -> str:
        """Name of the model to use."""
        return OPENSTACK_MODEL


class DnsFeature(OpenStackControlPlaneFeature):
    version = Version("0.0.1")
    nameservers: str | None

    def __init__(self, deployment: Deployment) -> None:
        super().__init__(
            "dns",
            deployment,
            tf_plan_location=TerraformPlanLocation.SUNBEAM_TERRAFORM_REPO,
        )
        self.nameservers = None

    def manifest_defaults(self) -> SoftwareConfig:
        """Feature software configuration."""
        return SoftwareConfig(
            charms={
                "designate-k8s": CharmManifest(channel=OPENSTACK_CHANNEL),
                "designate-bind-k8s": CharmManifest(channel=BIND_CHANNEL),
            }
        )

    def manifest_attributes_tfvar_map(self) -> dict:
        """Manifest attributes terraformvars map."""
        return {
            self.tfplan: {
                "charms": {
                    "designate-k8s": {
                        "channel": "designate-channel",
                        "revision": "designate-revision",
                        "config": "designate-config",
                    },
                    "designate-bind-k8s": {
                        "channel": "bind-channel",
                        "revision": "bind-revision",
                        "config": "bind-config",
                    },
                }
            }
        }

    def run_enable_plans(self) -> None:
        """Run plans to enable feature."""
        jhelper = JujuHelper(self.deployment.get_connected_controller())

        plan: list[BaseStep] = []
        if self.user_manifest:
            plan.append(
                AddManifestStep(self.deployment.get_client(), self.user_manifest)
            )
        tfhelper = self.deployment.get_tfhelper(self.tfplan)
        plan.extend(
            [
                TerraformInitStep(tfhelper),
                EnableOpenStackApplicationStep(tfhelper, jhelper, self),
                PatchBindLoadBalancerStep(self.deployment.get_client()),
            ]
        )

        run_plan(plan, console)
        click.echo(f"OpenStack {self.name!r} application enabled.")

    def set_application_names(self) -> list:
        """Application names handled by the terraform plan."""
        database_topology = self.get_database_topology()

        apps = ["bind", "designate", "designate-mysql-router"]
        if database_topology == "multi":
            apps.append("designate-mysql")

        return apps

    def set_tfvars_on_enable(self) -> dict:
        """Set terraform variables to enable the application."""
        return {
            "enable-designate": True,
            "nameservers": self.nameservers,
        }

    def set_tfvars_on_disable(self) -> dict:
        """Set terraform variables to disable the application."""
        return {"enable-designate": False}

    def set_tfvars_on_resize(self) -> dict:
        """Set terraform variables to resize the application."""
        return {}

    @click.command()
    @argument_with_deprecated_option(
        "nameservers",
        type=str,
        help="""\
        Space delimited list of nameservers. These are the nameservers that
        have been provided to the domain registrar in order to delegate
        the domain to DNS service. e.g. "ns1.example.com. ns2.example.com."
        """,
    )
    def enable_feature(self, nameservers: str) -> None:
        """Enable dns service.

        NAMESERVERS: Space delimited list of nameservers. These are the nameservers that
        have been provided to the domain registrar in order to delegate
        the domain to DNS service. e.g. "ns1.example.com. ns2.example.com."
        """
        nameservers_split = nameservers.split()
        for nameserver in nameservers_split:
            if nameserver[-1] != ".":
                raise click.ClickException(
                    "Nameservers must be fully qualified domain names ending with a dot"
                    f". {nameserver!r} is not valid."
                )
        self.nameservers = nameservers
        super().enable_feature()

    @click.command()
    def disable_feature(self) -> None:
        """Disable dns service."""
        super().disable_feature()

    @click.group()
    def dns_groups(self):
        """Manage dns."""

    async def bind_address(self) -> str | None:
        """Fetch bind address from juju."""
        model = OPENSTACK_MODEL
        application = "bind"
        jhelper = JujuHelper(self.deployment.get_connected_controller())
        model_impl = await jhelper.get_model(model)
        status = await model_impl.get_status([application])
        if application not in status["applications"]:
            return None
        return status["applications"][application].public_address

    @click.command()
    def dns_address(self) -> None:
        """Retrieve DNS service address."""
        with console.status("Retrieving IP address from DNS service ... "):
            bind_address = run_sync(self.bind_address())

            if bind_address:
                console.print(bind_address)
            else:
                _message = "No address found for DNS service."
                raise click.ClickException(_message)

    def commands(self) -> dict:
        """Dict of clickgroup along with commands."""
        commands = super().commands()
        try:
            enabled = self.enabled
        except ClusterServiceUnavailableException:
            LOG.debug(
                "Failed to query for feature status, is cloud bootstrapped ?",
                exc_info=True,
            )
            enabled = False

        if enabled:
            commands.update(
                {
                    "init": [{"name": "dns", "command": self.dns_groups}],
                    "init.dns": [{"name": "address", "command": self.dns_address}],
                }
            )
        return commands

    @property
    def k8s_application_data(self):
        """K8s application data."""
        return {
            "designate": ApplicationChannelData(
                channel=OPENSTACK_CHANNEL,
                tfvars_channel_var=None,
            ),
            "bind": ApplicationChannelData(
                channel=BIND_CHANNEL,
                tfvars_channel_var=None,
            ),
        }

    @property
    def tfvars_channel_var(self):
        """Terrform variable channel var."""
        return "designate-channel"
