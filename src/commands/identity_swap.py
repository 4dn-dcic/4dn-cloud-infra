import argparse
import boto3
from typing import List

from ..base import ConfigManager
from ..base import Settings
from dcicutils.beanstalk_utils import _create_foursight_new
from dcicutils.secrets_utils import assume_identity
from dcicutils.ecs_utils import ECSUtils


class IdentitySwapSetupError(Exception):
    pass


class CGAPIdentitySwap:
    """ Not implemented, as we do not do blue/green for CGAP. """
    pass


class FFIdentitySwap:
    """ Implements utilities necessary to identity swap 4DN production.
        Note that the orchestration of 4DN data/staging is specialized and will not generalize to
        standard use cases.
        If we would like to support blue/green for CGAP, a new infra layers will need to be created
        and this command will need to be reimplemented.
    """
    @staticmethod
    def _clean_identifier(identifier: str) -> str:
        """ Removes -, _ and lowercases the identifier so it will approximately match something in the
            generates names for ECS clusters
        """
        return identifier.replace('-', '').replace('_', '').lower()

    @classmethod
    def _resolve_cluster(cls, available_clusters: List[str], identifier: str) -> str:
        """ Takes in a list of cluster ARNs and an identifier and attempts to resolve a single cluster
            based on that identifier.
        """
        try:
            [identified_cluster] = [c for c in available_clusters if cls._clean_identifier(identifier) in c.lower()]
        except ValueError as e:
            raise IdentitySwapSetupError(f'Identifier {identifier} resolved ambiguous cluster! Try a more specific'
                                         f' identifier. Error: {e}')
        except Exception as e:
            raise IdentitySwapSetupError(f'Unknown error occurred acquiring clusters! Error: {e}')
        return identified_cluster

    @staticmethod
    def describe_services(ecs, cluster, services):
        """ Describes metadata on the given cluster, service pair
            TODO: refactor into dcicutils
        """
        result = ecs.client.describe_services(cluster=cluster, services=services)
        if result.get('failures', None):
            raise IdentitySwapSetupError(f'Got an error retrieving services for cluster {cluster}, response: {result}')
        return result

    @staticmethod
    def update_service(ecs, cluster, service, new_task_definition):
        """ Updates the given service configuration to utilize the new task definition
            TODO: refactor into dcicutils
        """
        return ecs.client.update_service(
            cluster=cluster,
            service=service,
            taskDefinition=new_task_definition
        )

    @classmethod
    def _align_services(cls, *, ecs: boto3.client, task_definitions: List[str], blue_cluster: str,
                        blue_services: List[str], green_cluster: str, green_services: List[str]) -> dict:
        """ Creates a dictionary mapping services to their current task definitions and the new desired task
            definition implementing the swap.
        """
        service_mapping = {}
        blue_service_metadata = cls.describe_services(ecs, cluster=blue_cluster, services=blue_services)
        green_service_metadata = cls.describe_services(ecs, cluster=green_cluster, services=green_services)
        for service in blue_service_metadata.get('services', []) + green_service_metadata.get('services', []):
            service_mapping[service['serviceArn']] = service['taskDefinition']
        # import pdb; pdb.set_trace()
        # filter task definitions to those included in the service mapping and the "mirror" counterparts
        # figure out which is configured where
        # return result mapping services --> new task definitions
        return service_mapping

    @classmethod
    def _execute_swap_plan(cls, swap_plan):
        """ Executes the swap plan by issuing service updates to the various services. """
        pass

    @classmethod
    def identity_swap(cls, *, blue: str, green: str):
        """ Triggers an ECS Service update for the blue and green clusters,
            swapping their tasks. """
        ecs = ECSUtils()
        app_kind = ConfigManager.get_config_setting(Settings.APP_KIND)
        if app_kind != 'ff':
            raise IdentitySwapSetupError(f'{app_kind} is not supported - must be ff')
        available_clusters = ecs.list_ecs_clusters()
        blue_cluster_arn = cls._resolve_cluster(available_clusters, blue)
        green_cluster_arn = cls._resolve_cluster(available_clusters, green)
        available_task_definitions = ecs.list_ecs_tasks()
        blue_services = ecs.list_ecs_services(cluster_name=blue_cluster_arn)
        green_services = ecs.list_ecs_services(cluster_name=green_cluster_arn)
        swap_plan = cls._align_services(ecs=ecs, task_definitions=available_task_definitions,
                                        blue_cluster=blue_cluster_arn, blue_services=blue_services,
                                        green_cluster=green_cluster_arn, green_services=green_services)
        cls._execute_swap_plan(swap_plan)
        # swap the foursight environments (ES URL)


def main():
    parser = argparse.ArgumentParser(description='Does an in-place task swap for all services in the given two FF'
                                                 ' envs.')
    parser.add_argument('blue', help='First env we are swapping', type=str)
    parser.add_argument('green', help='Second env we are swapping', type=str)
    args = parser.parse_args()

    with ConfigManager.validate_and_source_configuration():
        FFIdentitySwap.identity_swap(blue=args.blue, green=args.green)


if __name__ == '__main__':
    main()
