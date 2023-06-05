import argparse
import boto3
import io
import json
import sys
from typing import List, Union
from ..base import ConfigManager
from ..base import Settings
from ..exceptions import IdentitySwapSetupError
from dcicutils.lang_utils import conjoined_list
from dcicutils.ecs_utils import ECSUtils
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT, find_association, remove_prefix
from dcicutils.env_base import EnvBase
from dcicutils.s3_utils import s3Utils


def print_json(data, file=None, indent=2, default=str):
    file = file or sys.stdout
    PRINT(json.dumps(data, indent=indent, default=default), file=file)


def download_config(*, bucket, key):
    """ Downloads a config file from s3 """
    stream = io.BytesIO()
    s3 = boto3.client('s3')
    s3.download_fileobj(Fileobj=stream, Bucket=bucket, Key=key)
    return json.loads(stream.getvalue())


def upload_config(*, bucket, key, data: Union[str, dict], query=True):
    """ Uploads config intended for GLOBAL_ENV_BUCKET
        Note that this does not support S3_ENCRYPT_KEY_ID at the moment
    """
    heading(f"{key} in bucket {bucket} (OLD - ALREADY INSTALLED - REFORMATTED FOR DISPLAY)")
    print_json(download_config(bucket=bucket, key=key))
    heading(f"{key} in bucket {bucket} (NEW - TO BE UPLOADED)")
    print_json(data)
    if not query or yes_or_no(f"OK to upload?"):
        if isinstance(data, dict):
            data = json.dumps(data, indent=2, default=str) + "\n"
        stream = io.BytesIO(data.encode('utf-8'))
        s3 = boto3.client('s3')
        s3.upload_fileobj(Fileobj=stream, Bucket=bucket, Key=key)
        PRINT("Uploaded.")
    else:
        PRINT("NOT uploaded.")


def heading(text=None, wid=120):
    if text:
        PRINT("=" * wid)
        PRINT(" " * ((wid - len(text)) // 2) + text)
    PRINT("=" * wid)


DATA_URL = 'https://data.4dnucleome.org'
STAGING_URL = 'https://staging.4dnucleome.org'


class C4IdentitySwap:
    """ Methods and variables common to an identity swap procedure for both FF and CGAP are here """
    PORTAL = 'Portal'
    INDEXER = 'Indexer'
    INGESTER = 'Ingester'
    SERVICE_TYPES = [PORTAL, INDEXER, INGESTER]  # note caps are intentional and this set determines the valid services to swap

    @staticmethod
    def unseparate(identifier: str) -> str:
        """ Removes -, _ and lowercases the identifier, so it will approximately match something in the
            generates names for ECS clusters
        """
        # TODO: refactor into dcicutils.cloudformation_utils
        return identifier.replace('-', '').replace('_', '').lower()

    @classmethod
    def _resolve_cluster(cls, available_clusters: List[str], identifier: str) -> str:
        """ Takes in a list of cluster ARNs and an identifier and attempts to resolve a single cluster
            based on that identifier.
        """
        try:
            [identified_cluster] = [c for c in available_clusters if cls.unseparate(identifier) in c.lower()]
        except ValueError as e:
            raise IdentitySwapSetupError(f'Identifier {identifier} resolved ambiguous cluster!'
                                         f' Try a more specific identifier. Error: {e}')
        except Exception as e:
            raise IdentitySwapSetupError(f'Unknown error occurred acquiring clusters! Error: {e}')
        return identified_cluster

    @staticmethod
    def describe_services(ecs, cluster, services):
        """ Describes metadata on the given cluster, service pair """
        # TODO: refactor into dcicutils.ecs_utils
        result = ecs.client.describe_services(cluster=cluster, services=services)
        if result.get('failures', None):
            raise IdentitySwapSetupError(f'Got an error retrieving services for cluster {cluster}, response: {result}')
        return result

    @staticmethod
    def update_service(ecs, cluster, service, new_task_definition):
        """ Updates the given service configuration to utilize the new task definition """
        # TODO: refactor into dcicutils.ecs_utils
        return ecs.client.update_service(
            cluster=cluster,
            service=service,
            taskDefinition=new_task_definition
        )

    @classmethod
    def _resolve_target_service_type(cls, current_task_definition: str) -> str:
        """ Helper that determines the 'type' of the service (WRT our application)
            Note that this utility relies on the fact that services are not ambiguous ie: PortalIndexerService
            would be ambiguous in our scenario
        """
        for service_type in cls.SERVICE_TYPES:
            if service_type in current_task_definition:
                return service_type
        raise IdentitySwapSetupError(f'Could not resolve service type for {current_task_definition}.'
                                     f' Valid types are {conjoined_list(cls.SERVICE_TYPES)}.')


class CGAPIdentitySwap(C4IdentitySwap):
    """ Not implemented, as we do not do blue/green for CGAP. """
    pass


class FFIdentitySwap(C4IdentitySwap):
    """ Implements utilities necessary to identity swap 4DN production.
        Note that the orchestration of 4DN data/staging is specialized and will not generalize to
        standard use cases.
        If we would like to support blue/green for CGAP, new infra layers will need to be created
        and this command will need to be reimplemented.

        The identity swap for FF is not exactly a symmetric operation. Due to details of the ECS orchestration and
        limitations on ECS, mirror definitions exist that must be swapped in. So we define two semantically different
        operations that implement the swap in each direction.
            * Prod --> Mirror, where current task definitions match the cluster ie: cluster fourfront-production-green
              is associated with identity fourfront-production-green, in which case we would do a "mirror" swap to make
              cluster fourfront-production-green run the fourfront-production-blue mirror tasks.
            * Mirror --> Prod, where current task definitions mirror that of the cluster ie: cluster
              fourfront-production-green is associated with identity fourfront-production-blue via linking the services
              to the fourfront-production-blue mirror tasks, in which case we do a "prod" swap to return cluster
              fourfront-production-green to its original state where the task definitions match up.
    """
    @staticmethod
    def _is_mirror_task(task_definition: str) -> bool:
        """ Returns True if this task_definition is a Mirror task.
            Right now just checks if the identifier 'Mirror' is in the task_definition.
        """
        return 'Mirror' in task_definition

    @classmethod
    def _validate_service_state_is_prod(cls, service_mapping: dict) -> None:
        """ Helper that ensures no mirror definitions are linked in the service map. """
        for service, task_definition in service_mapping.items():
            if cls._is_mirror_task(task_definition):
                raise IdentitySwapSetupError(f'Attempted to do a mirror swap,'
                                             f' but current service_map contains mirror task definitions!'
                                             f' Rerun without --mirror.'
                                             f' Service mapping:\n{service_mapping}')

    @classmethod
    def _resolve_task_definition(cls, current_task_definition: str, all_task_definitions: List[str]) -> str:
        """ Figures out what the corresponding "opposite" task definition is from the set of task definitions.
            Precondition: all_task_definitions has been filtered to include only those relevant for the swap
                          scenario, meaning the caller must know whether we are doing a 'mirror' or 'prod' swap.
        """
        if 'blue' in current_task_definition:
            target_identity = 'green'
        elif 'green' in current_task_definition:
            target_identity = 'blue'
        else:
            raise IdentitySwapSetupError(f'Attempted to resolve mirror task definition from ambiguous definition'
                                         f' setup: cannot resolve mirror for {current_task_definition} given'
                                         f' {all_task_definitions}')
        target_service_type = cls._resolve_target_service_type(current_task_definition)
        candidate = sorted(list(filter(lambda d: target_identity in d and target_service_type in d,
                                       all_task_definitions)))[-1]  # last element will be latest revision
        return candidate

    @classmethod
    def _resolve_mirror_task_definition(cls, current_task_definition: str, all_task_definitions: List[str]) -> str:
        """ Helper that figures out what the corresponding 'mirror' task definition is given one to look for
            and the set of all task definitions.
        """
        if cls._is_mirror_task(current_task_definition):
            raise IdentitySwapSetupError(f'Found a current_task_definition in a mirror swap that is configured'
                                         f' to use a mirror task definition! Cluster may be in an inconsistent state'
                                         f' and should be repaired manually.')
        return cls._resolve_task_definition(current_task_definition, all_task_definitions)

    @classmethod
    def _determine_mirror_swap_plan(cls, service_mapping: dict, task_definitions: List[str]) -> dict:
        """ Determines the swap plan in the case we are doing a mirror swap. """
        swap_plan = {}
        for service, task_definition in service_mapping.items():
            swap_plan[service] = cls._resolve_mirror_task_definition(task_definition, task_definitions)
        return swap_plan

    @classmethod
    def _validate_service_state_is_mirror(cls, service_mapping: dict) -> None:
        """ Helper that ensures no prod definitions are linked in the service map. """
        for service, task_definition in service_mapping.items():
            if not cls._is_mirror_task(task_definition):
                raise IdentitySwapSetupError(f'Attempted to do a prod swap, but current service_map contains'
                                             f' prod task definitions! Rerun with --mirror. Service mapping:\n'
                                             f'{service_mapping}')

    @classmethod
    def _resolve_prod_task_definition(cls, current_task_definition: str, all_task_definitions: List[str]):
        """ Helper that figures out what the corresponding 'prod' task definition is given one to look for
            and the set of all task definitions.
        """
        if not cls._is_mirror_task(current_task_definition):
            raise IdentitySwapSetupError(f'Found a current_task_definition in a prod swap that is not configured'
                                         f' to use a mirror task definition! Cluster may be in an inconsistent state'
                                         f' and should be repaired manually.')
        return cls._resolve_task_definition(current_task_definition, all_task_definitions)

    @classmethod
    def _determine_prod_swap_plan(cls, service_mapping: dict, task_definitions: list) -> dict:
        """ Determines the swap plan in the case we are doing a prod swap. """
        swap_plan = {}
        for service, task_definition in service_mapping.items():
            swap_plan[service] = cls._resolve_prod_task_definition(task_definition, task_definitions)
        return swap_plan

    @classmethod
    def _determine_service_mapping(cls, ecs: boto3.client, blue_cluster: str, blue_services: List[str],
                                   green_cluster: str, green_services: List[str]) -> dict:
        """ Resolves the current state of mappings from services to task definitions. """
        service_mapping = {}
        blue_service_metadata = cls.describe_services(ecs, cluster=blue_cluster, services=blue_services)
        green_service_metadata = cls.describe_services(ecs, cluster=green_cluster, services=green_services)
        for service in blue_service_metadata.get('services', []) + green_service_metadata.get('services', []):
            service_mapping[service['serviceArn']] = service['taskDefinition']
        return service_mapping

    @classmethod
    def _determine_swap_plan(cls, *, ecs: boto3.client, task_definitions: List[str], blue_cluster: str,
                             blue_services: List[str], green_cluster: str, green_services: List[str],
                             mirror=False) -> dict:
        """ Resolves a dictionary mapping services to their current task definitions and returns a new dictionary
            mapping the new desired task state based on the current state and whether 'mirror' is set.
        """
        service_mapping = cls._determine_service_mapping(ecs, blue_cluster, blue_services, green_cluster,
                                                         green_services)
        mirror_definitions = list(filter(lambda d: 'Mirror' in d, task_definitions))
        standard_definitions = list(filter(lambda d: 'production' in d and 'Mirror' not in d, task_definitions))
        # swap prod task definitions for opposite "mirror" definitions
        if mirror:
            cls._validate_service_state_is_prod(service_mapping)
            return cls._determine_mirror_swap_plan(service_mapping, mirror_definitions)

        # swap mirror definitions for opposite "prod" definitions
        else:
            cls._validate_service_state_is_mirror(service_mapping)
            return cls._determine_prod_swap_plan(service_mapping, standard_definitions)

    @staticmethod
    def _pretty_print_swap_plan(swap_plan: dict) -> None:
        """ Helper that prints the swap_plan in a more readable format for manual review. """
        PRINT(f'New Service Mapping:')
        for service, task_definition in swap_plan.items():
            short_service_name = service.split('/')[-1]
            short_task_name = task_definition.split('/')[-1]
            PRINT(f'    {short_service_name} -----> {short_task_name}')

    @classmethod
    def _execute_swap_plan(cls, ecs, blue_cluster, green_cluster, swap_plan):
        """ Executes the swap plan by issuing service updates to the various services. """
        for service, new_task_definition in swap_plan.items():
            if 'blue' in service:
                cluster = blue_cluster
            else:
                cluster = green_cluster
            cls.update_service(ecs, cluster, service, new_task_definition)

    @classmethod
    def _update_foursight(cls, assure_prod_color=None, do_legacy=False) -> None:
        """ Triggers foursight update by updating data/staging env entries in GLOBAL_ENV_BUCKET. """
        with EnvBase.global_env_bucket_named('foursight-prod-envs'):

            heading("WARNING")
            PRINT("     This script will make changes to important files critical to")
            PRINT("     the correct operation of Fourfront. You should not do this casually.")
            heading()
            if yes_or_no("Are you sure you want to proceed?"):
                PRINT("OK, continuing.")
            else:
                PRINT("Aborting.")
                return

            if assure_prod_color is None:  # i.e., if we're just flipping and not trying to force a specific color
                main_ecosystem = "main.ecosystem"
                old_main = download_config(bucket='foursight-prod-envs', key=main_ecosystem)
                old_prd_env_name = old_main['prd_env_name']
                old_color = {'fourfront-production-blue': 'blue', 'fourfront-production-green': 'green'}[
                    old_prd_env_name]
                swapped_color = {'blue': 'green', 'green': 'blue'}[old_color]
                swapped_ecosystem_file = f"{swapped_color}.ecosystem"
                swapped_data = download_config(bucket='foursight-prod-envs', key=swapped_ecosystem_file)
                upload_config(bucket='foursight-prod-envs', key=main_ecosystem, data=swapped_data)
            else:
                raise NotImplementedError("need to add support for forcing a specific color")

            # if we want to make changes to the old (foursight-envs) bucket, pass do_legacy=True
            # note that this should no longer ever be necessary, but we keep for historical reasons
            if do_legacy:
                data = s3Utils.get_synthetic_env_config('data')  # Compute the real value from the real bucket
                data_env = data['ff_env']
                data['fourfront'] = DATA_URL
                data['ff_env'] = 'data'  # Synthetic value would say the full env name here, but we used to not do that.
                data[
                    'ecosystem'] = 'main.ecosystem'  # THe synthetic values don't have an ecosystem, so add it in old style.
                # It's not supposed to matter which format, but since the old tools were using this without http://
                # let's be maximally compatible. -kmp 23-Aug-2022
                data['es'] = remove_prefix('https://', data['es'])

                staging = s3Utils.get_synthetic_env_config('staging')  # Compute the real value from the real bucket
                staging_env = staging['ff_env']
                staging['fourfront'] = STAGING_URL
                staging[
                    'ff_env'] = 'staging'  # Synthetic value would say the full env name here, but we used to not do that.
                staging[
                    'ecosystem'] = 'main.ecosystem'  # THe synthetic values don't have an ecosystem, so add it in old style.
                # It's not supposed to matter which format, but since the old tools were using this without http://
                # let's be maximally compatible. -kmp 23-Aug-2022
                staging['es'] = remove_prefix('https://', staging['es'])

                main = download_config(bucket='foursight-envs', key='main.ecosystem')

                # There's an element that was 'stg_env' in foursight-envs main.ecosystem that I THINK should be stg_env_name,
                # but since it's harmless to keep both, and this is an interim tool intended to be maximally compatible,
                # let's add the one I think is right rather than replace it.
                # -kmp 23-Aug-2022
                new_main = {}
                for k, v in main.items():
                    if k == 'stg_env':  # This seems like a typo, but just in case it's old compatibility, leave it.
                        new_main[k] = v
                        new_main['stg_env_name'] = v
                    else:
                        new_main[k] = v
                main = new_main

                # Now finally do surgery to make sure we really know what env (green or blue) is dominant.
                # Must update both the top-level declaration and the environment mapping.
                # For now we are assuming that the declarations files for fourfront-production-blue
                # and fourfront-production-green need no adjustment. -kmp 23-Aug-2022

                main['prd_env_name'] = data_env
                main['stg_env'] = staging_env
                main['stg_env_name'] = staging_env

                public_url_table = main['public_url_table']

                data_entry = find_association(public_url_table, name='data')
                # data_entry['name'] is unchanged ('data')
                data_entry['url'] = DATA_URL
                data_entry['host'] = 'data.4dnucleome.org'
                data_entry['environment'] = data_env

                staging_entry = find_association(public_url_table, name='staging')
                # staging_entry['name'] is unchanged ('staging')
                staging_entry['url'] = STAGING_URL  # note https:// is recently preferred
                staging_entry['host'] = 'staging.4dnucleome.org'
                staging_entry['environment'] = staging_env

                green_env = 'fourfront-production-green'
                green = download_config(bucket='foursight-envs', key=green_env)
                green['fourfront'] = find_association(public_url_table, environment=green_env)['url']

                blue_env = 'fourfront-production-blue'
                blue = download_config(bucket='foursight-envs', key='fourfront-production-blue')
                blue['fourfront'] = find_association(public_url_table, environment=blue_env)['url']

                upload_config(bucket='foursight-envs', key='data', data=data)
                upload_config(bucket='foursight-envs', key='staging', data=staging)
                upload_config(bucket='foursight-envs', key=green_env, data=green)
                upload_config(bucket='foursight-envs', key=blue_env, data=blue)
                upload_config(bucket='foursight-envs', key='main.ecosystem', data=main)

    @classmethod
    def identity_swap(cls, *, blue: str, green: str, mirror: bool, do_legacy: bool) -> None:
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
        swap_plan = cls._determine_swap_plan(ecs=ecs, task_definitions=available_task_definitions,
                                             blue_cluster=blue_cluster_arn, blue_services=blue_services,
                                             green_cluster=green_cluster_arn, green_services=green_services,
                                             mirror=mirror)
        cls._pretty_print_swap_plan(swap_plan)
        confirm = input(f'Please confirm the above swap plan is correct. (yes|no) ').strip().lower() == 'yes'
        if confirm:
            cls._execute_swap_plan(ecs, blue_cluster_arn, green_cluster_arn, swap_plan)
            PRINT(f'Swap plan executed - new tasks should reflect within 5 minutes')

        # update GLOBAL_ENV_BUCKET
        cls._update_foursight(do_legacy=do_legacy)


def main():
    parser = argparse.ArgumentParser(
        description='Does an in-place task swap for all services in the given two FF envs.')
    parser.add_argument('blue', help='First env we are swapping', type=str)
    parser.add_argument('green', help='Second env we are swapping', type=str)
    parser.add_argument('--mirror', help='Whether or not we are doing a mirror swap.', action='store_true',
                        default=False)
    parser.add_argument('--do-legacy', help='Specify this to make changes to the legacy foursight-envs'
                                            ' bucket (should be unused)', action='store_true', default=False)
    args = parser.parse_args()

    with ConfigManager.validate_and_source_configuration():
        FFIdentitySwap.identity_swap(blue=args.blue, green=args.green, mirror=args.mirror, do_legacy=args.do_legacy)


if __name__ == '__main__':
    main()
