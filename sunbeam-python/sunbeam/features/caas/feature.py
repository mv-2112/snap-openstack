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
from pathlib import Path

import click
from packaging.version import Version
from pydantic import Field
from pydantic.dataclasses import dataclass
from rich.console import Console
from rich.status import Status

from sunbeam.clusterd.client import Client
from sunbeam.clusterd.service import ClusterServiceUnavailableException
from sunbeam.commands.configure import retrieve_admin_credentials
from sunbeam.core.common import BaseStep, Result, ResultType, run_plan
from sunbeam.core.deployment import Deployment
from sunbeam.core.juju import JujuHelper
from sunbeam.core.manifest import (
    CharmManifest,
    Manifest,
    SoftwareConfig,
    TerraformManifest,
)
from sunbeam.core.openstack import OPENSTACK_MODEL
from sunbeam.core.terraform import (
    TerraformException,
    TerraformHelper,
    TerraformInitStep,
)
from sunbeam.features.interface.v1.base import FeatureRequirement
from sunbeam.features.interface.v1.openstack import (
    OpenStackControlPlaneFeature,
    TerraformPlanLocation,
)
from sunbeam.versions import OPENSTACK_CHANNEL

LOG = logging.getLogger(__name__)
console = Console()


@dataclass
class CaasConfig:
    image_name: str | None = Field(default=None, description="CAAS Image name")
    image_url: str | None = Field(
        default=None, description="CAAS Image URL to upload to glance"
    )
    container_format: str | None = Field(
        default=None, description="Image container format"
    )
    disk_format: str | None = Field(default=None, description="Image disk format")
    properties: dict = Field(
        default={}, description="Properties to set for image in glance"
    )


class CaasConfigureStep(BaseStep):
    """Configure CaaS service."""

    def __init__(
        self,
        client: Client,
        tfhelper: TerraformHelper,
        manifest: Manifest,
        tfvar_map: dict,
    ):
        super().__init__(
            "Configure Container as a Service",
            "Configure Cloud for Container as a Service use",
        )
        self.client = client
        self.tfhelper = tfhelper
        self.manifest = manifest
        self.tfvar_map = tfvar_map

    def run(self, status: Status | None = None) -> Result:
        """Execute configuration using terraform."""
        try:
            override_tfvars = {}
            try:
                manifest_caas_config = self.manifest.software.extra[
                    "caas_config"
                ].model_dump()
                for caas_config_attribute, tfvar_name in self.tfhelper.tfvar_map.get(
                    "caas_config", {}
                ).items():
                    caas_config_attribute_ = manifest_caas_config.get(
                        caas_config_attribute
                    )
                    if caas_config_attribute_:
                        override_tfvars[tfvar_name] = caas_config_attribute_
            except AttributeError:
                # caas_config not defined in manifest, ignore
                pass

            self.tfhelper.update_tfvars_and_apply_tf(
                self.client, self.manifest, override_tfvars=override_tfvars
            )
        except TerraformException as e:
            LOG.exception("Error configuring Container as a Service feature.")
            return Result(ResultType.FAILED, str(e))

        return Result(ResultType.COMPLETED)


class CaasFeature(OpenStackControlPlaneFeature):
    version = Version("0.0.1")
    requires = {
        FeatureRequirement("secrets"),
        FeatureRequirement("orchestration"),
        FeatureRequirement("loadbalancer", optional=True),
    }

    def __init__(self, deployment: Deployment) -> None:
        super().__init__(
            "caas",
            deployment,
            tf_plan_location=TerraformPlanLocation.SUNBEAM_TERRAFORM_REPO,
        )
        self.configure_plan = "caas-setup"

    def manifest_defaults(self) -> SoftwareConfig:
        """Feature software configuration."""
        return SoftwareConfig(
            charms={"magnum-k8s": CharmManifest(channel=OPENSTACK_CHANNEL)},
            terraform={
                self.configure_plan: TerraformManifest(
                    source=Path(__file__).parent / "etc" / self.configure_plan
                ),
            },
        )

    def manifest_attributes_tfvar_map(self) -> dict:
        """Manifest attributes terraformvars map."""
        return {
            self.tfplan: {
                "charms": {
                    "magnum-k8s": {
                        "channel": "magnum-channel",
                        "revision": "magnum-revision",
                        "config": "magnum-config",
                    }
                }
            },
            self.configure_plan: {
                "caas_config": {
                    "image_name": "image-name",
                    "image_url": "image-source-url",
                    "container_format": "image-container-format",
                    "disk_format": "image-disk-format",
                    "properties": "image-properties",
                }
            },
        }

    def add_manifest_section(self, software_config: SoftwareConfig) -> None:
        """Adds manifest section."""
        caas_config = software_config.extra.get("caas_config")
        if caas_config is None:
            software_config.extra["caas_config"] = CaasConfig()
            return
        if isinstance(caas_config, CaasConfig):
            # Already instanciation of the schema, nothing to do
            return
        elif isinstance(caas_config, dict):
            software_config.extra["caas_config"] = CaasConfig(**caas_config)
        else:
            raise ValueError(f"Invalid caas_config in manifest: {caas_config!r}")

    def set_application_names(self) -> list:
        """Application names handled by the terraform plan."""
        apps = ["magnum", "magnum-mysql-router"]
        if self.get_database_topology() == "multi":
            apps.extend(["magnum-mysql"])

        return apps

    def set_tfvars_on_enable(self) -> dict:
        """Set terraform variables to enable the application."""
        return {
            "enable-magnum": True,
            **self.add_horizon_plugin_to_tfvars("magnum"),
        }

    def set_tfvars_on_disable(self) -> dict:
        """Set terraform variables to disable the application."""
        return {
            "enable-magnum": False,
            **self.remove_horizon_plugin_from_tfvars("magnum"),
        }

    def set_tfvars_on_resize(self) -> dict:
        """Set terraform variables to resize the application."""
        return {}

    @click.command()
    def enable_feature(self) -> None:
        """Enable Container as a Service feature."""
        super().enable_feature()

    @click.command()
    def disable_feature(self) -> None:
        """Disable Container as a Service feature."""
        super().disable_feature()

    @click.command()
    def configure(self):
        """Configure Cloud for Container as a Service use."""
        jhelper = JujuHelper(self.deployment.get_connected_controller())
        admin_credentials = retrieve_admin_credentials(jhelper, OPENSTACK_MODEL)

        tfhelper = self.deployment.get_tfhelper(self.configure_plan)
        tfhelper.env = (tfhelper.env or {}) | admin_credentials
        plan = [
            TerraformInitStep(tfhelper),
            CaasConfigureStep(
                self.deployment.get_client(),
                tfhelper,
                self.manifest,
                self.manifest_attributes_tfvar_map(),
            ),
        ]

        run_plan(plan, console)

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
                    "configure": [{"name": "caas", "command": self.configure}],
                }
            )
        return commands
