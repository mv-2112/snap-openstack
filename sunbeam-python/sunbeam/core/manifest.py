# Copyright (c) 2024 Canonical Ltd.
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

import copy
import logging
from pathlib import Path
from typing import Any

import pydantic
import yaml
from pydantic import Field
from snaphelpers import Snap

from sunbeam import utils
from sunbeam.clusterd.client import Client
from sunbeam.clusterd.service import (
    ClusterServiceUnavailableException,
    ManifestItemNotFoundException,
)
from sunbeam.core.common import (
    BaseStep,
    Result,
    ResultType,
    RiskLevel,
    Status,
    infer_risk,
)
from sunbeam.versions import MANIFEST_CHARM_VERSIONS, TERRAFORM_DIR_NAMES

LOG = logging.getLogger(__name__)
EMPTY_MANIFEST: dict[str, dict] = {"charms": {}, "terraform": {}}


def embedded_manifest_path(snap: Snap, risk: str) -> Path:
    return snap.paths.snap / "etc" / "manifests" / f"{risk}.yml"


class JujuManifest(pydantic.BaseModel):
    # Setting Field alias not supported in pydantic 1.10.0
    # Old version of pydantic is used due to dependencies
    # with older version of paramiko from python-libjuju
    # Newer version of pydantic can be used once the below
    # PR is released
    # https://github.com/juju/python-libjuju/pull/1005
    bootstrap_args: list[str] = Field(
        default=[], description="Extra args for juju bootstrap"
    )
    scale_args: list[str] = Field(
        default=[], description="Extra args for juju enable-ha"
    )


class CharmManifest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    channel: str | None = Field(default=None, description="Channel for the charm")
    revision: int | None = Field(
        default=None, description="Revision number of the charm"
    )
    # rocks: dict[str, str] | None = Field(
    #     default=None, description="Rock images for the charm"
    # )
    config: dict[str, Any] | None = Field(
        default=None, description="Config options of the charm"
    )
    # source: Path | None = Field(
    #     default=None, description="Local charm bundle path"
    # )


class TerraformManifest(pydantic.BaseModel):
    source: Path = Field(description="Path to Terraform plan")


class SoftwareConfig(pydantic.BaseModel):
    juju: JujuManifest = JujuManifest()
    charms: dict[str, CharmManifest] = {}
    terraform: dict[str, TerraformManifest] = {}

    model_config = pydantic.ConfigDict(
        extra="allow",
    )

    @classmethod
    def get_default(
        cls, feature_softwares: dict[str, "SoftwareConfig"] | None = None
    ) -> "SoftwareConfig":
        """Load default software config."""
        # TODO(gboutry): Remove Snap instanciation
        snap = Snap()
        charms = {
            charm: CharmManifest(channel=channel)
            for charm, channel in MANIFEST_CHARM_VERSIONS.items()
        }
        terraform = {
            tfplan: TerraformManifest(source=Path(snap.paths.snap / "etc" / tfplan_dir))
            for tfplan, tfplan_dir in TERRAFORM_DIR_NAMES.items()
        }
        if feature_softwares is None:
            LOG.debug("No features provided, skipping")
            return SoftwareConfig(charms=charms, terraform=terraform)

        extra = {}
        for feature, software in feature_softwares.items():
            for charm, charm_manifest in software.charms.items():
                if charm in charms:
                    raise ValueError(f"Feature {feature} overrides charm {charm}")
                charms[charm] = charm_manifest
            for tfplan, tf_manifest in software.terraform.items():
                if tfplan in terraform:
                    raise ValueError(f"Feature {feature} overrides tfplan {tfplan}")
                terraform[tfplan] = tf_manifest
            for key in software.extra:
                if key in extra:
                    raise ValueError(f"Feature {feature} overrides extra key {key}")
                extra[key] = software.extra[key]

        return SoftwareConfig(charms=charms, terraform=terraform, **extra)

    def validate_terraform_keys(self, default_software_config: "SoftwareConfig"):
        """Validate the terraform keys provided are expected."""
        if self.terraform:
            tf_keys = set(self.terraform.keys())
            all_tfplans = default_software_config.terraform.keys()
            if not tf_keys <= all_tfplans:
                raise ValueError(
                    f"Manifest Software Terraform keys should be one of {all_tfplans} "
                )

    def validate_charm_keys(self, default_software_config: "SoftwareConfig"):
        """Validate the charm keys provided are expected."""
        if self.charms:
            charms_keys = set(self.charms.keys())
            all_charms = default_software_config.charms.keys()
            if not charms_keys <= all_charms:
                raise ValueError(
                    f"Manifest Software charms keys should be one of {all_charms} "
                )

    def validate_against_default(
        self, default_software_config: "SoftwareConfig"
    ) -> None:
        """Validate the software config against the default software config."""
        self.validate_terraform_keys(default_software_config)
        self.validate_charm_keys(default_software_config)

    def merge(self, other: "SoftwareConfig") -> "SoftwareConfig":
        """Return a merged version of the software config."""
        juju = JujuManifest(
            **utils.merge_dict(self.juju.model_dump(), other.juju.model_dump())
        )
        charms: dict[str, CharmManifest] = utils.merge_dict(
            copy.deepcopy(self.charms), copy.deepcopy(other.charms)
        )
        terraform: dict[str, TerraformManifest] = utils.merge_dict(
            copy.deepcopy(self.terraform), copy.deepcopy(other.terraform)
        )
        extra = utils.merge_dict(copy.deepcopy(self.extra), copy.deepcopy(other.extra))
        return SoftwareConfig(juju=juju, charms=charms, terraform=terraform, **extra)

    @property
    def extra(self) -> dict:
        """Allow storing extra data."""
        if self.__pydantic_extra__ is None:
            self.__pydantic_extra__ = {}
        return self.__pydantic_extra__


class Manifest(pydantic.BaseModel):
    deployment: dict = {}
    software: SoftwareConfig = SoftwareConfig()

    @classmethod
    def get_default(
        cls,
        feature_softwares: dict[str, SoftwareConfig] | None = None,
    ) -> "Manifest":
        """Load manifest and override the default manifest."""
        software_config = SoftwareConfig.get_default(feature_softwares)
        return Manifest(software=software_config)

    @classmethod
    def from_file(cls, file: Path) -> "Manifest":
        """Load manifest from file."""
        with file.open() as f:
            return Manifest.model_validate(yaml.safe_load(f))

    def merge(self, other: "Manifest") -> "Manifest":
        """Merge the manifest with the provided manifest."""
        deployment = utils.merge_dict(
            copy.deepcopy(self.deployment), copy.deepcopy(other.deployment)
        )
        software = self.software.merge(other.software)

        return Manifest(deployment=deployment, software=software)

    def validate_against_default(self, default_manifest: "Manifest") -> None:
        """Validate the manifest against the default manifest."""
        self.software.validate_against_default(default_manifest.software)


class AddManifestStep(BaseStep):
    """Add Manifest file to cluster database.

    This step writes the manifest file to cluster database if:
    - The user provides a manifest file.
    - The user clears the manifest.
    - The risk level is not stable.
    Any other reason will be skipped.
    """

    manifest_content: dict[str, dict] | None

    def __init__(
        self,
        client: Client,
        manifest_file: Path | None = None,
        clear: bool = False,
    ):
        super().__init__("Write Manifest to database", "Writing Manifest to database")
        self.client = client
        self.manifest_file = manifest_file
        self.clear = clear
        self.manifest_content = None
        self.snap = Snap()

    def is_skip(self, status: Status | None = None) -> Result:
        """Skip if the user provided manifest and the latest from db are same."""
        risk = infer_risk(self.snap)
        try:
            embedded_manifest = yaml.safe_load(
                embedded_manifest_path(self.snap, risk).read_bytes()
            )
            if self.manifest_file:
                with self.manifest_file.open("r") as file:
                    self.manifest_content = yaml.safe_load(file)
            elif self.clear:
                self.manifest_content = EMPTY_MANIFEST
        except (yaml.YAMLError, IOError) as e:
            LOG.debug("Failed to load manifest", exc_info=True)
            return Result(ResultType.FAILED, str(e))

        latest_manifest = None
        try:
            latest_manifest = self.client.cluster.get_latest_manifest()
        except ManifestItemNotFoundException:
            if self.manifest_content is None:
                if risk == RiskLevel.STABLE:
                    # only save risk manifest when not stable,
                    # and no manifest was found in db
                    return Result(ResultType.SKIPPED)
                else:
                    self.manifest_content = embedded_manifest
        except ClusterServiceUnavailableException as e:
            LOG.debug("Failed to fetch latest manifest from clusterd", exc_info=True)
            return Result(ResultType.FAILED, str(e))

        if self.manifest_content is None:
            return Result(ResultType.SKIPPED)

        if (
            latest_manifest
            and yaml.safe_load(latest_manifest.get("data", {})) == self.manifest_content
        ):
            return Result(ResultType.SKIPPED)

        return Result(ResultType.COMPLETED)

    def run(self, status: Status | None = None) -> Result:
        """Write manifest to cluster db."""
        try:
            id = self.client.cluster.add_manifest(
                data=yaml.safe_dump(self.manifest_content)
            )
            return Result(ResultType.COMPLETED, id)
        except Exception as e:
            LOG.debug(e)
            return Result(ResultType.FAILED, str(e))
