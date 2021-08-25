import argparse
import boto3

from dcicutils.ecs_utils import CGAP_ECS_REGION
from dcicutils.misc_utils import PRINT


def list_clusters(client):
    """ Uses ECSUtils to get cluster information. """
    return client.list_clusters().get('clusterArns', [])


def kick_cluster_update(client, cluster):
    """ Triggers a cluster update, forcing new deployments of all services. """
    services = client.list_services(cluster=cluster).get('serviceArns', [])
    for service in services:
        client.update_service(cluster=cluster, service=service,
                              forceNewDeployment=True)


def main():
    """ Triggers a production deployment. """
    parser = argparse.ArgumentParser(description='Deployment Script')
    parser.add_argument('--list', action='store_true', help='Whether to list ECS cluster options and exit')
    parser.add_argument('--kick', action='store_true', default=False,
                        help='pass this option to kick the deployment task')
    parser.add_argument('--env', help='name of ECS cluster to trigger deployment')
    args = parser.parse_args()

    # XXX: replace logic with ECSUtils
    client = boto3.client('ecs', region_name=CGAP_ECS_REGION)
    if args.list:
        PRINT(list_clusters(client))
        exit(0)
    elif args.kick:
        if not args.env:
            PRINT('No env specified!')
            exit(1)
        kick_cluster_update(client, args.env)
    else:
        PRINT('No action option specified - exiting.')
        exit(0)


if __name__ == '__main__':
    main()
