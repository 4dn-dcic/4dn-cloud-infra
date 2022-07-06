import boto3
import json
import re
from typing import Optional
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from .aws_context import AwsContext
from .misc_utils import (obfuscate, print_exception, should_obfuscate)


class Aws(AwsContext):

    _DEACTIVATED_SECRET_VALUE_PREFIX = "DEACTIVATED:"

    def get_secret_value(self, secret_name: str, secret_key_name: str) -> str:
        """
        Returns the value of the given secret key name
        within the given secret name in the AWS secrets manager.

        :param secret_name: AWS secret name.
        :param secret_key_name: AWS secret key name.
        :return: Secret key value if found or None if not found.
        """
        with super().establish_credentials():
            secrets_manager = boto3.client("secretsmanager")
            secret_values = secrets_manager.get_secret_value(SecretId=secret_name)
            secret_values_json = json.loads(secret_values["SecretString"])
            secret_key_value = secret_values_json.get(secret_key_name)
            return secret_key_value

    def update_secret_key_value(self,
                                secret_name: str,
                                secret_key_name: str,
                                secret_key_value: str,
                                show: bool = False) -> bool:
        """
        Updates the AWS secret value for the given secret key name within the given secret name.
        If the given secret key value does not yet exist it will be created.
        If the given secret key value is None then the given secret key will be "deactivated",
        where this means that its old value will be prepended with the string "DEACTIVATED:".
        This is a command-line INTERACTIVE process, prompting the user for info/confirmation.

        :param secret_name: AWS secret name.
        :param secret_key_name: AWS secret key name to update.
        :param secret_key_value: AWS secret key value to update to; if None secret key will be deactivated.
        :param show: True to show any displayed sensitive values in plaintext.
        :return: True if succeeded otherwise false.
        """

        def print_secret(prefix: str, name: str, key_name: str, key_value: str) -> None:
            if not key_value:
                PRINT(f"{prefix} value of AWS secret {name}.{key_name} has no value.")
                return
            suffix = " is deactivated" if key_value.startswith(self._DEACTIVATED_SECRET_VALUE_PREFIX) else ""
            if should_obfuscate(key_name) and not show:
                PRINT(f"{prefix} value of AWS secret looks like it is sensitive: {name}.{key_name}")
                if yes_or_no("Show in plaintext?"):
                    PRINT(f"{prefix} value of AWS secret {name}.{key_name}{suffix}: {key_value}")
                else:
                    PRINT(f"{prefix} value of AWS secret {name}.{key_name}{suffix}: {obfuscate(key_value)}")
            else:
                PRINT(f"{prefix} value of AWS secret {name}.{key_name}{suffix}: {key_value}")

        PRINT()
        with super().establish_credentials():
            secrets_manager = boto3.client("secretsmanager")
            try:
                # To update an individual secret key value we need to get the entire JSON
                # associated with the given secret name, update the specific element for
                # the given secret key name with the new given value, and write the updated
                # JSON back as the secret value for the given secret name.
                try:
                    secret_value = secrets_manager.get_secret_value(SecretId=secret_name)
                except Exception:
                    PRINT(f"AWS secret name does not exist: {secret_name}")
                    return False
                secret_value_json = json.loads(secret_value["SecretString"])
                secret_key_value_current = secret_value_json.get(secret_key_name)
                if secret_key_value is None:
                    # Deactivating secret key value.
                    if secret_key_value_current is None:
                        PRINT(f"AWS secret {secret_name}.{secret_key_name} does not exist."
                              f" Nothing to deactivate.")
                        return False
                    print_secret("Current", secret_name, secret_key_name, secret_key_value_current)
                    if secret_key_value_current.startswith(self._DEACTIVATED_SECRET_VALUE_PREFIX):
                        PRINT(f"AWS secret {secret_name}.{secret_key_name} is already deactivated."
                              f" Nothing to do.")
                        return False
                    secret_key_value = self._DEACTIVATED_SECRET_VALUE_PREFIX + secret_key_value_current
                    action = "deactivate"
                else:
                    if secret_key_value_current is None:
                        # Creating new secret key value.
                        PRINT(f"AWS secret {secret_name}.{secret_key_name} does not yet exist.")
                        action = "create"
                    else:
                        # Updating existing secret key value.
                        print_secret("Current", secret_name, secret_key_name, secret_key_value_current)
                        action = "update"
                        if secret_key_value_current == secret_key_value:
                            PRINT(f"New value of AWS secret ({secret_name}.{secret_key_name}) same as current one."
                                  f" Nothing to update.")
                            return False
                    print_secret("New", secret_name, secret_key_name, secret_key_value)
                yes = yes_or_no(f"Are you sure you want to {action} AWS secret {secret_name}.{secret_key_name}?")
                if yes:
                    secret_value_json[secret_key_name] = secret_key_value
                    secrets_manager.update_secret(SecretId=secret_name, SecretString=json.dumps(secret_value_json))
                    return True
            except Exception as e:
                print_exception(e)
            return False

    def find_iam_user_name(self, user_name_pattern: str) -> Optional[str]:
        """
        Returns the first AWS IAM user name in which
        matches the given (regular expression) pattern.

        :param user_name_pattern: Regular expression for user name.
        :return: Matched user name or None if none found.
        """
        with super().establish_credentials():
            iam = boto3.resource("iam")
            users = iam.users.all()
            for user in users:
                user_name = user.name
                if re.match(user_name_pattern, user_name):
                    return user_name
        return None

    def get_customer_managed_kms_keys(self) -> list:
        """
        Returns the customer managed AWS KMS key IDs.

        :return: List of customer managed KMS key IDs; empty list of none found.
        """
        kms_keys = []
        with super().establish_credentials():
            kms = boto3.client("kms")
            for key in kms.list_keys()["Keys"]:
                key_id = key["KeyId"]
                key_description = kms.describe_key(KeyId=key_id)
                key_metadata = key_description["KeyMetadata"]
                key_manager = key_metadata["KeyManager"]
                if key_manager == "CUSTOMER":
                    # TODO: If multiple keys (for some reason) silently pick the most recently created one (?)
                    # key_creation_date = key_metadata["CreationDate"]
                    kms_keys.append(key_id)
        return kms_keys

    def get_elasticsearch_endpoint(self, aws_credentials_name: str) -> Optional[str]:
        """
        Returns the endpoint (host:port) for the ElasticSearch instance associated
        with the given AWS credentials name (e.g. cgap-supertest).

        :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
        :return: Endpoint (host:port) for ElasticSearch or None if not found.
        """
        with super().establish_credentials():
            # TODO: Get this name from somewhere in 4dn-cloud-infra.
            elasticsearch_instance_name = f"es-{aws_credentials_name}"
            elasticsearch = boto3.client("opensearch")
            domain_names = elasticsearch.list_domain_names()["DomainNames"]
            domain_name = [domain_name for domain_name in domain_names
                           if domain_name["DomainName"] == elasticsearch_instance_name]
            if domain_name is None or len(domain_name) != 1:
                return None
            domain_name = domain_name[0]["DomainName"]
            domain_description = elasticsearch.describe_domain(DomainName=domain_name)
            domain_status = domain_description["DomainStatus"]
            domain_endpoints = domain_status["Endpoints"]
            domain_endpoint_options = domain_status["DomainEndpointOptions"]
            domain_endpoint_vpc = domain_endpoints["vpc"]
            # NOTE: This EnforceHTTPS is from datastore.py/elasticsearch_instance.
            domain_endpoint_https = domain_endpoint_options["EnforceHTTPS"]
            if domain_endpoint_https:
                domain_endpoint = f"{domain_endpoint_vpc}:443"
            else:
                domain_endpoint = f"{domain_endpoint_vpc}:80"
            return domain_endpoint

    def create_user_access_key(self, user_name: str, show: bool = False) -> (Optional[str], Optional[str]):
        """
        Create an AWS security access key pair for the given IAM user name.
        This is a command-line INTERACTIVE process, prompting the user for info/confirmation.
        because this is the only time it will ever be available.

        :param user_name: AWS IAM user name.
        :param show: True to show any displayed sensitive values in plaintext.
        :return: Tuple containing the access key ID and associated secret.
        """
        with super().establish_credentials():
            iam = boto3.resource("iam")
            user = [user for user in iam.users.all() if user.name == user_name]
            if not user or len(user) <= 0:
                PRINT("AWS user not found for security access key pair creation: {user_name}")
                return None, None
            if len(user) > 1:
                PRINT("Multiple AWS users found for security access key pair creation: {user_name}")
                return None, None
            user = user[0]
            existing_keys = boto3.client("iam").list_access_keys(UserName=user.name)
            if existing_keys:
                existing_keys = existing_keys.get("AccessKeyMetadata")
                if existing_keys and len(existing_keys) > 0:
                    if len(existing_keys) == 1:
                        PRINT(f"AWS IAM user ({user.name}) already has an access key defined:")
                    else:
                        PRINT(f"AWS IAM user ({user.name}) already has {len(existing_keys)} access keys defined:")
                    for existing_key in existing_keys:
                        existing_access_key_id = existing_key["AccessKeyId"]
                        existing_access_key_create_date = existing_key["CreateDate"]
                        PRINT(f"- {existing_access_key_id} (created:"
                              f" {existing_access_key_create_date.astimezone().strftime('%Y-%m-%d %H:%M:%S')})")
                    yes = yes_or_no("Do you still want to create a new access key?")
                    if not yes:
                        return None, None
            yes = yes_or_no(f"Create AWS security access key pair for AWS IAM user: {user.name} ?")
            if yes:
                key_pair = user.create_access_key_pair()
                PRINT(f"- Created AWS Access Key ID ({user.name}): {key_pair.id}")
                PRINT(f"- Created AWS Secret Access Key ({user.name}): {obfuscate(key_pair.secret, show)}")
                return key_pair.id, key_pair.secret
            return None, None

    def find_iam_role_arns(self, role_arn_pattern: str) -> list:
        """
        Returns the list of AWS IAM role ARNs which match the given role ARN pattern.
        Created for the update-kms-policy script.

        :param role_arn_pattern: Regular expression to match role ARNs.
        :return: List of matching AWS IAM role ARNs or empty list of none found.
        """
        found_roles = []
        with super().establish_credentials():
            iam = boto3.client("iam")
            roles = iam.list_roles()["Roles"]
            for role in roles:
                role_arn = role["Arn"]
                if re.match(role_arn_pattern, role_arn):
                    found_roles.append(role_arn)
        return found_roles

    def get_kms_key_policy(self, key_id: str) -> dict:
        """
        Returns JSON for the KMS key policy for the given KMS key ID.
        Created for the update-kms-policy script.

        :param key_id: KMS key ID.
        :return: Policy for given KMS key ID or None if not found.
        """
        with super().establish_credentials():
            kms = boto3.client("kms")
            key_policy = kms.get_key_policy(KeyId=key_id, PolicyName="default")["Policy"]
            key_policy_json = json.loads(key_policy)
            return key_policy_json

    @staticmethod
    def get_kms_key_policy_principals(key_policy_json: dict, sid_pattern: str) -> list:
        """
        Returns the AWS principals list for the specific KMS key policy within the
        given KMS key policy JSON, whose statement ID (sid) matches the given sid_pattern.

        :param key_policy_json: JSON for a KMS key policy.
        :param sid_pattern: Statement ID (sid) pattern to match the specific policy.
        :return: List of KMS key policy principals.
        """
        key_policy_statements = key_policy_json["Statement"]
        for key_policy_statement in key_policy_statements:
            key_policy_statement_id = key_policy_statement["Sid"]
            if re.match(sid_pattern, key_policy_statement_id):
                return key_policy_statement["Principal"]["AWS"]

    @staticmethod
    def amend_kms_key_policy(key_policy_json: dict, sid_pattern: str, additional_roles: list) -> int:
        """
        Amends the specific KMS key policy for the given key_policy_json (IN PLACE), whose statement
        ID (sid) matches the given sid_pattern, with the roles contained in the given additional_roles
        list. Will not add if already present. Returns the number of roles actually added.
        Created for the update-kms-policy script.

        :param key_policy_json: JSON for a KMS key policy.
        :param sid_pattern: Statement ID (sid) pattern to match the specific policy.
        :param additional_roles: List of AWS IAM role ARNs to add to the roles for the specified KMS policy.
        :return: Number of roles from the given addition roles actually added.
        """
        nadded = 0
        key_policy_statement_principals = Aws.get_kms_key_policy_principals(key_policy_json, sid_pattern)
        for additional_role in additional_roles:
            if additional_role not in key_policy_statement_principals:
                key_policy_statement_principals.append(additional_role)
                nadded += 1
        key_policy_statement_principals.sort()
        return nadded

    def update_kms_key_policy(self, key_id: str, key_policy_json: dict) -> None:
        """
        Updates the specific AWS KMS key policy for the given key_id with the given JSON,
        representing the new (complete) key policy for the KMS key.
        Created for the update-kms-policy script.

        :param key_id: KMS key ID.
        :param key_policy_json: JSON for the KMS key policy.
        """
        with super().establish_credentials():
            kms = boto3.client("kms")
            key_policy_string = json.dumps(key_policy_json)
            kms.put_key_policy(KeyId=key_id, Policy=key_policy_string, PolicyName="default")

    def find_security_group_id(self, security_group_name: str) -> Optional[str]:
        """
        Returns the AWS security group ID for the given AWS security group name.

        :param security_group_name: AWS security group name.
        :return: AWS security group ID for the given AWS security group name.
        """
        with super().establish_credentials():
            ec2 = boto3.client('ec2')
            security_group_filter = [{"Name": "tag:Name", "Values": [security_group_name]}]
            security_groups = ec2.describe_security_groups(Filters=security_group_filter)
            if not security_groups:
                return None
            security_groups = security_groups.get("SecurityGroups")
            if not security_groups or len(security_groups) != 1:
                return None
            security_group_id = security_groups[0].get("GroupId")
            return security_group_id

    def create_outbound_security_group_rule(self, security_group_id: str, security_group_rule: list) -> dict:
        """
        Creates the given AWS security group outbound rule for the given AWS security group ID.

        :param security_group_id: AWS security group ID.
        :param security_group_rule: AWS outbound security group rule.
        :return: Response from the boto3 call to create the outbound security group rule.
        """
        with super().establish_credentials():
            ec2 = boto3.client('ec2')
            return ec2.authorize_security_group_egress(GroupId=security_group_id,
                                                       IpPermissions=security_group_rule)

    def create_inbound_security_group_rule(self, security_group_id: str, security_group_rule: list) -> dict:
        """
        Creates the given AWS security group rule for the given AWS security group ID.

        :param security_group_id: AWS security group ID.
        :param security_group_rule: AWS inbound security group rule.
        :return: Response from the boto3 call to create the inbound security group rule.
        """
        with super().establish_credentials():
            ec2 = boto3.client('ec2')
            return ec2.authorize_security_group_ingress(GroupId=security_group_id,
                                                        IpPermissions=security_group_rule)
