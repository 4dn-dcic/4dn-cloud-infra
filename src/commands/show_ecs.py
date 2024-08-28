from __future__ import annotations
from boto3 import client as BotoClient
from botocore.client import BaseClient as BotoEcs
from collections import namedtuple
import os
import sys
from termcolor import colored
from typing import List, Literal, Optional, Tuple, Union


class AwsEcs:

    BLUE = "blue"
    GREEN = "green"
    BLUE_OR_GREEN = [BLUE, GREEN]

    PORTAL = "Portal"
    INDEXER = "Indexer"
    INGESTER = "Ingester"
    TYPES = [PORTAL, INDEXER, INGESTER]

    class Cluster:
        def __init__(self, cluster_arn: str, initialize: bool = False, ecs: Optional[AwsEcs] = None) -> None:
            self.cluster_arn = cluster_arn or ""
            self.cluster_name = AwsEcs._arn_to_name(cluster_arn)
            self._services = None
            self._ecs = ecs if isinstance(ecs, AwsEcs) else AwsEcs()
            self._ecs._note_name(self.cluster_name)
            if initialize is True:
                _ = self.services
        @property  # noqa
        def services(self) -> List[AwsEcs.Service]:
            if self._services is None:
                self._services = []
                if service_names := self._ecs._list_services(cluster_name=self.cluster_name):
                    if service_descriptions := self._ecs._describe_services(cluster_name=self.cluster_name,
                                                                            service_names=service_names):
                        for service_description in service_descriptions:
                            self._services.append(AwsEcs.Service(
                                cluster=self,
                                service_name=service_description.get("serviceName"),
                                service_arn=service_description.get("serviceArn"),
                                task_definition=service_description.get("taskDefinition"),
                                ecs=self._ecs))
                    self._services = self._sort_services_by_type(self._services)
            return self._services
        @property  # noqa
        def running_tasks(self) -> List[object]:  # noqa
            return self._ecs._list_running_tasks(cluster_name=self.cluster_name)
        @property  # noqa
        def is_blue(self) -> bool:
            return AwsEcs._is_blue(self.cluster_name)
        @property  # noqa
        def is_green(self) -> bool:
            return AwsEcs._is_green(self.cluster_name)
        @property  # noqa
        def blue_or_green(self) -> str:
            return AwsEcs._blue_or_green(self.cluster_name)
        @property  # noqa
        def annotation(self) -> str:
            if blue_or_green := self.blue_or_green:
                return self._ecs._terminal_color(blue_or_green.upper(), blue_or_green)
            return ""
        @staticmethod  # noqa
        def _sort_services_by_type(services: List[AwsEcs.Service]) -> List[AwsEcs.Service]:
            sorted_services = []
            for service_type in AwsEcs.TYPES:
                for service in services:
                    if service.type == service_type:
                        sorted_services.append(service)
            return sorted_services

    class Service:
        def __init__(self, cluster: AwsEcs.Cluster, service_name: str, service_arn: str,
                     task_definition: Optional[Union[AwsEcs.TaskDefinition, str]] = None,
                     ecs: Optional[AwsEcs] = None) -> None:
            self.cluster = cluster if isinstance(cluster, AwsEcs.Cluster) else None
            self.service_name = service_name or ""
            self.service_arn = service_arn or ""
            self.task_definition = (task_definition if isinstance(task_definition, AwsEcs.TaskDefinition)
                                    else (AwsEcs.TaskDefinition(task_definition, ecs=ecs)
                                          if isinstance(task_definition, str) else None))
            self._ecs = ecs if isinstance(ecs, AwsEcs) else AwsEcs()
            self._ecs._note_name(self.service_name)
        @property  # noqa
        def running_tasks(self) -> List[object]:  # noqa
            return self._ecs._list_running_tasks(cluster_name=self.cluster.cluster_name, service_name=self.service_name)
        @property  # noqa
        def is_blue(self) -> bool:
            return AwsEcs._is_blue(self.service_name)
        @property  # noqa
        def is_green(self) -> bool:
            return AwsEcs._is_green(self.service_name)
        @property  # noqa
        def blue_or_green(self) -> str:
            return AwsEcs._blue_or_green(self.service_name)
        @property  # noqa
        def type(self) -> str:
            return AwsEcs._type(self.service_name)
        @property  # noqa
        def is_mirrored(self) -> bool:
            return (self.is_blue and self.task_definition.is_green) or (self.is_green and self.task_definition.is_blue)
        @property  # noqa
        def annotation(self) -> str:
            annotation = ""
            if self.type:
                if annotation:
                    annotation += " | "
                annotation = self.type.upper()
            if self.blue_or_green:
                if annotation:
                    annotation += " | "
                annotation += self._ecs._terminal_color(self.blue_or_green.upper(), self.blue_or_green)
            if self.is_mirrored and False:
                if annotation:
                    annotation += " | "  # " ▶ "
                annotation += "MIRROR"
            return f"{annotation}" if annotation else ""
        def __str__(self) -> str:  # noqa
            annotation = self.annotation
            return f"{self.service_name}{f' {annotation}' if annotation else ''}"

    class TaskDefinition:
        def __init__(self, task_definition_arn: str, ecs: Optional[AwsEcs] = None) -> None:
            self.task_definition_arn = task_definition_arn or ""
            self.task_definition_name = AwsEcs._arn_to_name(task_definition_arn)
            self._ecs = ecs if isinstance(ecs, AwsEcs) else AwsEcs()
            self._ecs._note_name(self.task_definition_name)
        @property  # noqa
        def is_blue(self) -> bool:
            return AwsEcs._is_blue(self.task_definition_arn)
        @property  # noqa
        def is_green(self) -> bool:
            return AwsEcs._is_green(self.task_definition_arn)
        @property  # noqa
        def blue_or_green(self) -> str:
            return AwsEcs._blue_or_green(self.task_definition_arn)
        @property  # noqa
        def type(self) -> str:
            return AwsEcs._type(self.task_definition_name)
        @property  # noqa
        def annotation(self) -> str:
            annotation = ""
            if self.type:
                if annotation:
                    annotation += " | "
                annotation = self.type.upper()
            if self.blue_or_green:
                if annotation:
                    annotation += " | "
                annotation += self._ecs._terminal_color(self.blue_or_green.upper(), self.blue_or_green)
            return f"{annotation}" if annotation else ""
        def __str__(self) -> str:  # noqa
            annotation = self.annotation
            return f"{self.task_definition_name}{f' {annotation}' if annotation else ''}"

    class TaskDefinitionSwap:
        def __init__(self, service: AwsEcs.Service, new_task_definition: AwsEcs.TaskDefinition) -> None:
            self.service = service
            self.new_task_definition = new_task_definition

    def __init__(self, blue_green: bool = False, initialize: bool = False,
                 nocolor: bool = False, boto_ecs: Optional[BotoEcs] = None) -> None:
        self._boto_ecs = BotoClient("ecs") if not isinstance(boto_ecs, BotoEcs) else boto_ecs
        self._blue_green = blue_green is True
        self._clusters = None
        self._nocolor = nocolor is True
        self._names = []
        if initialize is True:
            self._clusters = self._get_clusters(initialize=True)

    @property
    def clusters(self) -> List[Cluster]:
        if self._clusters is None:
            self._clusters = self._get_clusters()
        return self._clusters

    def format_name(self, value: str, versioned: bool = True, shortened: bool = False) -> str:
        if versioned is False:
            value = self._unversioned_name(value)
        if (shortened is True) and isinstance(value, str) and (prefix := AwsEcs._longest_common_prefix(self._names)):
            if value.startswith(prefix):
                value = value[len(prefix):]
        return value

    @property
    def account_info(self) -> Optional[object]:
        boto_sts = BotoClient("sts")
        boto_iam = BotoClient("iam")
        try:
            account_number = boto_sts.get_caller_identity()["Account"]
            account_alias = None
            try:
                account_alias = boto_iam.list_account_aliases()["AccountAliases"][0]
            except Exception:
                pass
            return namedtuple("aws_account_info", ["account_number", "account_alias"])(account_number, account_alias)
        except Exception:
            return None

    def identity_swap_plan(self) -> Tuple[Optional[List[AwsEcs.TaskDefinitionSwap]], Optional[str]]:
        identity_swaps, error = self._identity_swap(swap=False)
        if error:
            return None, error
        return identity_swaps, None

    def identity_swap_preview(self) -> Tuple[Optional[AwsEcs], Optional[str]]:
        identity_swapped, error = self._identity_swap(swap=True)
        if error:
            return None, error
        return identity_swapped, None

    def _identity_swap(self, swap: bool = False) -> Tuple[Optional[Union[List[AwsEcs.TaskDefinitionSwap],
                                                                         AwsEcs]], Optional[str]]:

        # Get the blue cluster.
        if not (blue_cluster := [cluster for cluster in self.clusters if cluster.is_blue]):
            return None, "Blue cluster not found."
        elif len(blue_cluster) > 1:
            return None, f"Mutliple ({len(blue_cluster)}) blue clusters not found: TODO"
        blue_cluster = blue_cluster[0]
        blue_services = blue_cluster.services

        # Get the green cluster.
        if not (green_cluster := [cluster for cluster in self.clusters if cluster.is_green]):
            return None, "Green cluster not found."
        elif len(green_cluster) > 1:
            return None, f"Mutliple ({len(green_cluster)}) green clusters not found: TODO"
        green_cluster = green_cluster[0]
        green_services = green_cluster.services

        # Sanity check service count.
        if len(blue_services) != len(green_services):
            return None, f"Different number of blue ({len(blue_services)}) and green ({len(green_services)}) services."

        if swap is not True:
            identity_swaps = []

        for service_type in AwsEcs.TYPES:
            blue_services_of_type = [service for service in blue_services if service.type == service_type]
            green_services_of_type = [service for service in green_services if service.type == service_type]
            if len(blue_services_of_type) != len(green_services_of_type):
                return None, (f"Different number of blue ({len(blue_services)}) and"
                              f" green ({len(green_services)}) {service_type.upper()} services.")
            for index, blue_service in enumerate(blue_services_of_type):
                green_service = green_services_of_type[index]
                blue_service_task_definition = blue_service.task_definition
                green_service_task_definition = green_service.task_definition
                if swap is True:
                    # This is the actual swap (of the data - not actually in AWS of course) right here:
                    green_service.task_definition = blue_service_task_definition
                    blue_service.task_definition = green_service_task_definition
                else:
                    # Record the proposed swap in list of TaskDefinitionSwap objects.
                    identity_swaps.append(AwsEcs.TaskDefinitionSwap(green_service, blue_service_task_definition))
                    identity_swaps.append(AwsEcs.TaskDefinitionSwap(blue_service, green_service_task_definition))

        if swap is True:
            return self, None
        else:
            return identity_swaps, None

    def print(self, shortened_names: bool = False, versioned_names: bool = False) -> AwsEcs:
        for cluster in self.clusters:
            cluster_running_task_count = len(cluster.running_tasks)
            if services := cluster.services:
                cluster_annotation = cluster.annotation
                print(f"\n- CLUSTER: {self.format_name(cluster.cluster_name, shortened=shortened_names)}"
                      f"{f' | {cluster_annotation}' if cluster_annotation else ''}"
                      f"{f' | ({cluster_running_task_count})' if cluster_running_task_count > 0 else ''}")  # noqa
                for service in services:
                    service_running_task_count = len(service.running_tasks)
                    service_mirror_indicator = '□' if service.is_mirrored else '-'
                    service_name = self.format_name(service.service_name,
                                                    shortened=shortened_names, versioned=versioned_names)
                    service_annotation = service.annotation
                    task_definition_name = self.format_name(service.task_definition.task_definition_name,
                                                            shortened=shortened_names, versioned=versioned_names)
                    task_definition_annotation = service.task_definition.annotation
                    print(f"  {service_mirror_indicator} SERVICE: {service_name}"
                          f"{f' | {service_annotation}' if service_annotation else ''}")
                    print(f"    -- TASK: {task_definition_name}"
                          f"{f' | {task_definition_annotation}' if task_definition_annotation else ''}"
                          f"{f' | ({service_running_task_count})' if service_running_task_count > 0 else ''}")
        print("")

    def _note_name(self, value: str) -> None:
        if isinstance(value, str) and value and (value.lower() != "default"):
            self._names.append(value)

    def _get_clusters(self, initialize: bool = False) -> List[Cluster]:
        clusters = []
        for cluster_arn in self._list_clusters():
            if (not self._blue_green) or AwsEcs._blue_or_green(cluster_arn):
                clusters.append(AwsEcs.Cluster(cluster_arn, initialize=initialize, ecs=self))
        clusters = sorted(clusters, key=lambda item: (not item.blue_or_green, item.cluster_name))
        return clusters

    def _list_clusters(self) -> List[str]:
        try:
            return self._boto_ecs.list_clusters().get("clusterArns", [])
        except Exception:
            return []

    def _list_services(self, cluster_name: str) -> List[dict]:
        try:
            return self._boto_ecs.list_services(cluster=cluster_name).get("serviceArns", [])
        except Exception:
            return []

    def _list_running_tasks(self, cluster_name: str, service_name: Optional[str] = None) -> List[dict]:
        try:
            if isinstance(service_name, str) and service_name:
                return self._boto_ecs.list_tasks(cluster=cluster_name,
                                                 serviceName=service_name, desiredStatus="RUNNING")["taskArns"]
            else:
                return self._boto_ecs.list_tasks(cluster=cluster_name, desiredStatus="RUNNING")["taskArns"]
        except Exception:
            return []

    def _describe_services(self, cluster_name: str, service_names: List[str]) -> List[str]:
        try:
            return self._boto_ecs.describe_services(cluster=cluster_name, services=service_names)["services"]
        except Exception:
            return []

    @staticmethod
    def _is_blue(value: str) -> bool:
        return AwsEcs._blue_or_green(value) == AwsEcs.BLUE

    @staticmethod
    def _is_green(value: str) -> bool:
        return AwsEcs._blue_or_green(value) == AwsEcs.GREEN

    @staticmethod
    def _blue_or_green(value: str) -> Literal[AwsEcs.BLUE_OR_GREEN]:
        if isinstance(value, str) and (value := value.lower()):
            blues = value.count(AwsEcs.BLUE)
            greens = value.count(AwsEcs.GREEN)
            if (blues > 0) or (greens > 0):
                return AwsEcs.BLUE if blues > greens else (AwsEcs.GREEN if greens > blues else None)
            return None

    @staticmethod
    def _is_portal(value: str) -> bool:
        return AwsEcs._type(value) == AwsEcs.PORTAL

    @staticmethod
    def _is_indexer(value: str) -> bool:
        return AwsEcs._type(value) == AwsEcs.INDEXER

    @staticmethod
    def _is_ingester(value: str) -> bool:
        return AwsEcs._type(value) == AwsEcs.INGESTER

    @staticmethod
    def _type(value: str) -> Optional[Literal[AwsEcs.TYPES]]:
        if isinstance(value, str):
            if AwsEcs.PORTAL in value:
                return AwsEcs.PORTAL
            elif AwsEcs.INDEXER in value:
                return AwsEcs.INDEXER
            elif AwsEcs.INGESTER in value:
                return AwsEcs.INGESTER
        return None

    @staticmethod
    def _arn_to_name(arn: str) -> str:
        return arn.split("/")[-1] if isinstance(arn, str) and "/" in arn else ""

    @staticmethod
    def _unversioned_name(value: str) -> str:
        if isinstance(value, str) and ((colon := value.rfind(":")) > 0):
            return value[:colon]
        return value

    @staticmethod
    def _longest_common_prefix(strings: List[str]) -> str:
        if not (isinstance(strings, list) and strings and isinstance(prefix := strings[0], str)):
            return ""
        for value in strings[1:]:
            if not isinstance(value, str):
                return ""
            while not value.startswith(prefix):
                prefix = prefix[:-1]
                if not prefix:
                    return ""
        return prefix

    def _terminal_color(self, value: str, color: str) -> str:
        if self._nocolor:
            return value
        return colored(value, color.lower(), attrs=["dark", "bold", "underline"])


def usage() -> None:
    print("usage: awsecs [--bluegreen] [--swap] [--short] [--versioned] [--aws aws-profile-name]")
    exit(1)


def main():

    blue_green = False
    shortened_names = False
    versioned_names = False
    identity_swap = False
    nocolor = False

    argi = 0
    while argi < len(argv := sys.argv[1:]):
        arg = argv[argi]
        if ((arg == "--bluegreen") or (arg == "-bluegreen") or (arg == "bluegreen") or
            (arg == "--greenblue") or (arg == "-greenblue") or (arg == "greenblue") or
            (arg == "--bg") or (arg == "-bg") or (arg == "bg") or
            (arg == "--gb") or (arg == "-gb") or (arg == "gb")):  # noqa
            # Show only blue/green clusters/services/task-definitions.
            blue_green = True
        elif (arg == "--short") or (arg == "-short") or (arg == "short"):
            # Display shortened names for easier viewing if possible; removes longest common prefix.
            shortened_names = True
        elif (arg == "--versioned") or (arg == "-versioned") or (arg == "versioned"):
            # Dot not lop off the ":n" from the end of task definition names.
            versioned_names = True
        elif ((arg == "--identity-swap") or (arg == "-identity-swap") or (arg == "identity-swap") or
              (arg == "--swap") or (arg == "-swap") or (arg == "swap")):
            # Show identity swap plan.
            identity_swap = True
        elif (arg == "--nocolor") or (arg == "-nocolor") or (arg == "nocolor"):
            nocolor = True
        elif (arg == "--aws") or (arg == "-aws") or (arg == "--env") or (arg == "-env"):
            # Profile name from ~/.aws/config file.
            if ((argi := argi + 1) >= len(argv)) or (aws_profile := argv[argi]).startswith("-"):
                usage()
            os.environ["AWS_PROFILE"] = aws_profile
        else:
            usage()
        argi += 1

    if identity_swap:
        blue_green = True

    ecs = AwsEcs(blue_green=blue_green, nocolor=nocolor)

    if not (ecs_account_info := ecs.account_info):
        print("AWS credentials do not appear to be working.")
        exit(1)

    print(f"Showing current ECS cluster info for AWS account: {ecs_account_info.account_number}"
          f"{f' ({ecs_account_info.account_alias})' if ecs_account_info.account_alias else ''} ...")

    ecs.print(shortened_names=shortened_names, versioned_names=versioned_names)

    if identity_swap:
        identity_swaps, error = ecs.identity_swap_plan()
        if error:
            print(error)
            exit(1)
        print(f"Showing proposed ECS identity swap plan for AWS account: {ecs_account_info.account_number}"
              f"{f' ({ecs_account_info.account_alias})' if ecs_account_info.account_alias else ''} ...")
        for swap in identity_swaps:
            service_name = ecs.format_name(swap.service.service_name,
                                           versioned=versioned_names, shortened=shortened_names)
            service_annotation = swap.service.annotation
            task_definition_name = ecs.format_name(swap.service.task_definition.task_definition_name,
                                                   versioned=versioned_names, shortened=shortened_names)
            task_definition_annotation = swap.service.task_definition.annotation
            new_task_definition_name = ecs.format_name(swap.new_task_definition.task_definition_name,
                                                       versioned=versioned_names, shortened=shortened_names)
            new_task_definition_annotation = swap.new_task_definition.annotation
            print(f"\n- SERVICE: {service_name}{f' {service_annotation}' if service_annotation else ''}")
            print(f"  - CURRENT TASK: {task_definition_name}"
                  f"{f' | {task_definition_annotation}' if task_definition_annotation else ''}")
            print(f"     ▶▶ NEW TASK: {new_task_definition_name}"
                  f"{f' | {new_task_definition_annotation}' if new_task_definition_annotation else ''}")
        print()

        print("It would look like this after the swap:")
        identity_swaps, error = ecs.identity_swap_preview()
        if error:
            print(error)
            exit(1)
        identity_swaps.print(shortened_names=shortened_names, versioned_names=versioned_names)


if __name__ == "__main__":
    main()
