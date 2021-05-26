# This file contains constants mapping to the environment variables
# that contain the desired information. Setting any of these values
# in config.json will have the effect of setting the configuration
# option for the orchestration. The only options listed that are
# currently unavailable are: ES_MASTER_COUNT, ES_MASTER_TYPE, IDENTITY

# General constants
DEPLOYING_IAM_USER = 'deploying_iam_user'
ENV_NAME = 'ENCODED_BS_ENV'

# RDS Configuration Options
RDS_INSTANCE_SIZE = 'rds.instance_size'
RDS_STORAGE_SIZE = 'rds.storage_size'
RDS_DB_NAME = 'rds.db_name'
RDS_AZ = 'rds.az'

# ES Configuration Options
ES_MASTER_COUNT = 'elasticsearch.master_node_count'
ES_MASTER_TYPE = 'elasticsearch.master_node_type'
ES_DATA_COUNT = 'elasticsearch.data_node_count'
ES_DATA_TYPE = 'elasticsearch.data_node_type'
ES_VOLUME_SIZE = 'elasticsearch.volume_size'

# ECS Configuration Options
ECS_WSGI_COUNT = 'ecs.wsgi.count'
ECS_WSGI_CPU = 'ecs.wsgi.cpu'
ECS_WSGI_MEM = 'ecs.wsgi.mem'
ECS_INDEXER_COUNT = 'ecs.indexer.count'
ECS_INDEXER_CPU = 'ecs.indexer.cpu'
ECS_INDEXER_MEM = 'ecs.indexer.mem'
ECS_INGESTER_COUNT = 'ecs.ingester.count'
ECS_INGESTER_CPU = 'ecs.ingester.cpu'
ECS_INGESTER_MEM = 'ecs.ingester.mem'
IDENTITY = 'identity'  # XXX: import from dcicutils

# Foursight Configuration Options
CHECK_RUNNER = 'CHECK_RUNNER'
