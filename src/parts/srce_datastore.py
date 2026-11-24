import re

from awacs.aws import Action, PolicyDocument, Principal, Statement
from troposphere import AccountId, GetAtt, Join, Output, Template
from troposphere.iam import Policy, Role

from .datastore import C4Datastore, C4DatastoreExports
from .iam import C4IAMExports
from .srce_network import C4SRCEDBNetworkExports
from ..base import ConfigManager
from ..constants import C4SRCEDatastoreBase, Settings


# The IAM stack uses SHARING='ecosystem' and is shared across all environments in the account.
# With the default ecosystem qualifier 'main', it is always named c4-iam-main-stack.
SRCE_IAM_STACK_NAME = 'c4-iam-main-stack'


class C4SRCEDatastore(C4SRCEDatastoreBase, C4Datastore):
    """
    SRCE variant of C4Datastore. Creates RDS, OpenSearch, S3, and SQS resources
    inside the IT-provided Database VPC by swapping in C4SRCEDBNetworkExports.

    C4SRCEDBNetworkExports uses 'DBNetworkStackNameParameter' as its reference key,
    so the generated template will look up subnet and security group IDs from the
    'srce-network-db' CloudFormation stack rather than the standard network stack.

    The IAM stack (c4-iam-main-stack) is ecosystem-scoped and shared across all
    environments in the account. Its name is set as the Default for IAMStackNameParameter
    so deployments resolve correctly without relying on ecosystem config resolution.
    """
    NETWORK_EXPORTS = C4SRCEDBNetworkExports()

    # STACK_NAME_TOKEN / STACK_TITLE_TOKEN / DEFAULT_RDS_POSTGRES_VERSION come from
    # C4SRCEDatastoreBase, which src/names.py also uses to compute this stack's names before
    # orchestration (setup-remaining-secrets). Keeping one source stops the two from drifting.

    def build_template(self, template: Template) -> Template:
        template = super().build_template(template)
        # Patch the IAM stack name parameter to default to the shared main stack.
        # c4-iam-main-stack uses SHARING='ecosystem' and is not env-prefixed, unlike
        # the SRCE datastore/network stacks. This default matches the deployed stack.
        iam_param_key = self.IAM_EXPORTS.reference_param_key
        if iam_param_key in template.parameters:
            template.parameters[iam_param_key].Default = SRCE_IAM_STACK_NAME

        upload_role = self.s3_upload_role()
        template.add_resource(upload_role)

        export_name = C4DatastoreExports.S3_UPLOAD_ROLE_ARN
        template.add_output(Output(
            self.name.logical_id(export_name),
            Description='SRCE S3 file upload role ARN',
            Value=GetAtt(upload_role, 'Arn'),
            Export=self.EXPORTS.export(export_name),
        ))
        return template

    @classmethod
    def s3_upload_role_name(cls) -> str:
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        role_name = f'{cls.S3_UPLOAD_ROLE_PREFIX}{env_name}'
        if len(role_name) > 64:
            raise ValueError(f'SRCE S3 upload role name exceeds the IAM 64-character limit: {role_name!r}')
        return role_name

    def s3_upload_role_arn(self):
        return Join('', ['arn:aws:iam::', AccountId, ':role/', self.s3_upload_role_name()])

    def s3_encrypt_key(self):
        key = super().s3_encrypt_key()
        key.KeyPolicy['Statement'].append({
            'Sid': 'Allow SRCE S3 upload role to use the key',
            'Effect': 'Allow',
            'Principal': {'AWS': '*'},
            'Action': [
                'kms:Decrypt',
                'kms:GenerateDataKey',
            ],
            'Resource': '*',
            'Condition': {'ArnEquals': {'aws:PrincipalArn': self.s3_upload_role_arn()}},
        })
        tibanna_roles = self.tibanna_tiger_role_arns()
        if tibanna_roles:
            # Appended last, so every existing statement keeps its position and content.
            key.KeyPolicy['Statement'].append({
                'Sid': 'Allow Tibanna tiger roles to use the key',
                'Effect': 'Allow',
                'Principal': {'AWS': '*'},
                'Action': list(self.TIBANNA_KEY_ACTIONS),
                'Resource': '*',
                'Condition': {'ArnEquals': {'aws:PrincipalArn': tibanna_roles}},
            })
        return key

    #: The roles tibanna_smaht's deploy_tiger creates for env E (tibanna/iam_utils.py role_types/role_suffix with
    #: tibanna_smaht's tiger lambda names): tibanna_tiger_E_<suffix>. These are exactly the role ARNs deploy_tiger
    #: would otherwise append to the 'Allow use of the key' statement with PutKeyPolicy.
    TIBANNA_TIGER_ROLE_SUFFIXES = ('for_ec2', 'states', 'run_task', 'check_task', 'start_run', 'update_ffmeta',
                                   'update_cost')
    #: The actions of the 'Allow use of the key' statement those roles would have joined.
    TIBANNA_KEY_ACTIONS = ('kms:Encrypt', 'kms:Decrypt', 'kms:ReEncrypt*', 'kms:GenerateDataKey*', 'kms:DescribeKey')
    _TIBANNA_ENV = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_+=,.@-]*$')

    def tibanna_tiger_role_arns(self):
        """ datastore.tibanna_tiger_env -> the exact ARNs of that env's seven tibanna_tiger roles, or None when unset.
            Exact ARNs (ArnEquals), not a wildcard, so no other role -- including another Tibanna env's -- matches;
            the roles need not exist yet (aws:PrincipalArn is a condition, not a principal KMS must resolve). """
        env = ConfigManager.get_config_setting(Settings.DATASTORE_TIBANNA_TIGER_ENV, default=None)
        if env is None:
            return None
        env = str(env).strip()
        longest = f'tibanna_tiger_{env}_update_ffmeta'
        if not self._TIBANNA_ENV.match(env) or len(longest) > 64:
            raise ValueError(f'{Settings.DATASTORE_TIBANNA_TIGER_ENV} must be an IAM-name-safe env such that'
                             f' {longest!r} fits the 64-character role name limit, not {env!r}')
        return [Join('', ['arn:aws:iam::', AccountId, f':role/tibanna_tiger_{env}_{suffix}'])
                for suffix in self.TIBANNA_TIGER_ROLE_SUFFIXES]

    def s3_upload_role(self) -> Role:
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        bucket_name = self.resolve_bucket_name(ConfigManager.AppBucketTemplate.FILES)
        statements = [
            {
                'Effect': 'Allow',
                'Action': ['s3:GetObject', 's3:PutObject', 's3:AbortMultipartUpload'],
                'Resource': f'arn:aws:s3:::{bucket_name}/*',
            },
            {
                'Effect': 'Allow',
                'Action': 's3:ListBucket',
                'Resource': f'arn:aws:s3:::{bucket_name}',
            },
        ]
        if ConfigManager.get_config_setting(Settings.S3_BUCKET_ENCRYPTION, default=True):
            statements.append({
                'Effect': 'Allow',
                'Action': [
                    'kms:Decrypt',
                    'kms:GenerateDataKey',
                ],
                'Resource': GetAtt(self.s3_encrypt_key(), 'Arn'),
            })
        return Role(
            self.name.logical_id('S3UploadRole'),
            RoleName=self.s3_upload_role_name(),
            AssumeRolePolicyDocument=PolicyDocument(
                Version='2012-10-17',
                Statement=[Statement(
                    Effect='Allow',
                    Action=[Action('sts', 'AssumeRole')],
                    Principal=Principal('AWS', Join('', [
                        'arn:aws:iam::', AccountId, ':role/',
                        self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
                    ])),
                )],
            ),
            Policies=[Policy(
                PolicyName=f'{env_name}-S3FileUploadAccess',
                PolicyDocument={'Version': '2012-10-17', 'Statement': statements},
            )],
            Tags=self.tags.cost_tag_array(),
        )
