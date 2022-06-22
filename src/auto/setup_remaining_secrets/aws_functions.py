import boto3
import json
import re
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from .aws_context import AwsContext
from .utils import (obfuscate, should_obfuscate)

class AwsFunctions(AwsContext):

    def get_secret_value(self, secret_name: str, secret_key_name: str) -> str:
        """
        Returns the value of the given secret key name
        within the given secret name in the AWS secrets manager.

        :param secret_name: AWS secret name.
        :param secret_key_name: AWS secret key name.
        :return: Secret key value if found or None if not found.
        """
        with super().establish_credentials():
            secrets_manager = boto3.client('secretsmanager')
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
        :param show: True to show in plaintext any displayed secret values. 
        :return: True if succeeded otherwise false.
        """

        DEACTIVATED_PREFIX = "DEACTIVATED:"

        def print_secret(prefix: str,  secret_name: str, secret_key_name: str, secret_key_value: str, show: bool) -> None:
            if not secret_key_value:
                PRINT(f"{prefix} value of AWS secret {secret_name}.{secret_key_name} has no value.")
                return
            suffix = " is deactivated" if secret_key_value.startswith(DEACTIVATED_PREFIX) else ""
            if should_obfuscate(secret_key_name) and not show:
                PRINT(f"{prefix} value of AWS secret looks like it is sensitive: {secret_name}.{secret_key_name}")
                yes = yes_or_no("Show in plaintext?")
                if yes:
                    PRINT(f"{prefix} value of AWS secret {secret_name}.{secret_key_name}{suffix}: {secret_key_value}")
                else:
                    PRINT(f"{prefix} value of AWS secret {secret_name}.{secret_key_name}{suffix}: {obfuscate(secret_key_value)}")
            else:
                PRINT(f"{prefix} value of AWS secret {secret_name}.{secret_key_name}{suffix}: {secret_key_value}")

        with super().establish_credentials():
            secrets_manager = boto3.client('secretsmanager')
            try:
                # To update an individual secret key value we need to get the entire JSON
                # associated with the given secret name, update the specific element for
                # the given secret key name with the new given value, and write the updated
                # JSON back as the secret value for the given secret name.
                try:
                    secret_value = secrets_manager.get_secret_value(SecretId=secret_name)
                except:
                    PRINT(f"AWS secret name does not exist: {secret_name}")
                    return False
                secret_value_json = json.loads(secret_value["SecretString"])
                secret_key_value_current = secret_value_json.get(secret_key_name)
                if secret_key_value is None:
                    # Deactivating secret key value.
                    if secret_key_value_current is None:
                        PRINT(f"AWS secret {secret_name}.{secret_key_name} does not exist. Nothing to deactivate.")
                        return False
                    print_secret("Current", secret_name, secret_key_name, secret_key_value_current, show)
                    if secret_key_value_current.startswith(DEACTIVATED_PREFIX):
                        PRINT(f"AWS secret {secret_name}.{secret_key_name} is already deactivated. Nothing to do.")
                        return False
                    secret_key_value = DEACTIVATED_PREFIX + secret_key_value_current
                    action = "deactivate"
                else:
                    if secret_key_value_current is None:
                        # Creating new secret key value.
                        PRINT(f"AWS secret {secret_name}.{secret_key_name} does not yet exist.")
                        action = "create"
                    else:
                        # Updating existing secret key value.
                        print_secret("Current", secret_name, secret_key_name, secret_key_value_current, show)
                        action = "update"
                        if secret_key_value_current == secret_key_value:
                            PRINT(f"New value of AWS secret ({secret_name}.{secret_key_name}) same as current one. Nothing to update.")
                            return False
                    print_secret("New", secret_name, secret_key_name, secret_key_value, show)
                yes = yes_or_no(f"Are you sure you want to {action} AWS secret {secret_name}.{secret_key_name}?")
                if yes:
                    secret_value_json[secret_key_name] = secret_key_value
                    secrets_manager.update_secret(SecretId=secret_name, SecretString=json.dumps(secret_value_json))
                    return True
            except Exception as e:
                PRINT(f"EXCEPTION: {str(e)}")
            return False

    def find_iam_user_name(self, user_name_pattern: str) -> str:
        """
        Returns the first AWS IAM user name in which
        matches the given (regular expression) pattern.

        :param user_name_pattern: Regular expression for user name.
        :return: Matched user name or None if none found.
        """
        with super().establish_credentials():
            iam = boto3.resource('iam')
            users = iam.users.all()
            for user in sorted(users, key=lambda user: user.name):
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
                most_recent_creation_date = None
                if key_manager == "CUSTOMER":
                    # TODO: If multiple keys (for some reason) silently pick the most recently created one (?)
                    key_creation_date = key_metadata["CreationDate"]
                    kms_keys.append(key_id)
        return kms_keys

    def get_elasticsearch_endpoint(self, aws_credentials_name: str) -> str:
        """
        Returns the endpoint (host:port) for the ElasticSearch instance associated
        with the given AWS credentials name (e.g. cgap-supertest).

        :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
        :return: Endpoint (host:port) for ElasticSearch or None if not found.
        """
        with super().establish_credentials():
            # TODO: Get this name from somewhere in 4dn-cloud-infra.
            elasticsearch_instance_name = f"es-{aws_credentials_name}"
            elasticsearch = boto3.client('opensearch')
            domain_names = elasticsearch.list_domain_names()["DomainNames"]
            domain_name = [domain_name for domain_name in domain_names if domain_name["DomainName"] == elasticsearch_instance_name]
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

    def create_user_access_key(self, user_name: str, show: bool = False) -> [str,str]:
        """
        Create an AWS security access key pair for the given IAM user name.
        This is a command-line INTERACTIVE process, prompting the user for info/confirmation.
        because this is the only time it will ever be available.

        :param user_name: AWS IAM user name.
        :param show: True to show in plaintext any displayed secret values. 
        :return: Tuple containing the access key ID and associated secret.
        """
        with super().establish_credentials():
            iam = boto3.resource('iam')
            user = [user for user in iam.users.all() if user.name == user_name]
            if not user or len(user) <= 0:
                PRINT("AWS user not found for security access key pair creation: {user_name}")
                return None, None
            if len(user) > 1:
                PRINT("Multiple AWS users found for security access key pair creation: {user_name}")
                return None, None
            user = user[0]
            existing_keys = boto3.client('iam').list_access_keys(UserName=user.name)
            if existing_keys:
                existing_keys = existing_keys.get("AccessKeyMetadata")
                if existing_keys and len(existing_keys) > 0:
                    if len(existing_keys) ==  1:
                        PRINT(f"AWS IAM user ({user.name}) already has an access key defined:")
                    else:
                        PRINT(f"AWS IAM user ({user.name}) already has {len(existing_keys)} access keys defined:")
                    for existing_key in existing_keys:
                        existing_access_key_id = existing_key["AccessKeyId"]
                        existing_access_key_create_date = existing_key["CreateDate"]
                        PRINT(f"- {existing_access_key_id} (created: {existing_access_key_create_date.astimezone().strftime('%Y-%m-%d %H:%M:%S')})")
                    yes = yes_or_no("Do you still want to create a new access key?")
                    if not yes:
                        return None, None
            PRINT(f"Creating AWS security access key pair for AWS IAM user: {user.name}")
            yes = yes_or_no(f"Continue?")
            if yes:
                key_pair = user.create_access_key_pair()
                PRINT(f"- Created AWS Access Key ID ({user.name}): {key_pair.id}")
                PRINT(f"- Created AWS Secret Access Key ({user.name}): {key_pair if show else obfuscate(key_pair.secret)}")
                return key_pair.id, key_pair.secret
            return None, None

    # TODO: This is for what will be a different script to update the KMS policy with foursight roles.
    def find_iam_role_names(self, role_name_pattern: str) -> list:
        """
        Returns the list of AWS IAM role ARNs which match the given role name pattern.

        :param role_name_pattern: Regular expression to match role names
        :return: List of matching AWS IAM role ARNs or empty list of none found.
        """
        found_roles = []
        with super().establish_credentials():
            iam = boto3.client('iam')
            roles = iam.list_roles()["Roles"]
            for role in roles:
                role_name = role["Arn"]
                if re.match(role_name_pattern, role_name):
                    found_roles.append(role_name)
        return found_roles

    # TODO: This is for what will be a different script to update the KMS policy with foursight roles.
    def get_kms_key_policy(self, key_id: str) -> dict:
        """
        Returns JSON for the KMS key policy for the given KMS key ID.
        :param key_id: KMS key ID.
        :return: Policy for given KMS key ID or None if not found.
        """
        with super().establish_credentials():
            kms = boto3.client("kms")
            key_policy = kms.get_key_policy(KeyId=key_id, PolicyName="default")["Policy"]
            key_policy_json = json.loads(key_policy)
            return key_policy_json

    # TODO: This is for what will be a different script to update the KMS policy with foursight roles.
    def _amend_kms_key_policy(self, key_policy_json: dict, sid_pattern: str, additional_roles: list) -> int:
        """
        Amends the specific KMS key policy for the given key_policy_json (IN PLACE), whose statement ID (sid)
        matches the given sid_pattern, with the roles contained in the given additional_roles list.
        Will not add if already present. Returns the number of roles actually added.

        :param key_policy_json: JSON for a KMS key policy.
        :param sid_pattern: Statement ID (sid) pattern to match the specific policy.
        :param additional_roles: List of AWS IAM role ARNs to add to the roles for the specified KMS policy.
        :return: Number of roles from the given addition roles actually added.
        """
        nadded = 0
        key_policy_statements = key_policy_json["Statement"]
        for key_policy_statement in key_policy_statements:
            key_policy_statement_id = key_policy_statement["Sid"]
            if re.match(sid_pattern, key_policy_statement_id):
                key_policy_statement_principals =  key_policy_statement["Principal"]["AWS"]
                for additional_role in additional_roles:
                    if additional_role not in key_policy_statement_principals:
                        key_policy_statement_principals.append(additional_role)
                        nadded += 1
        return nadded

    # TODO: This is for what will be a different script to update the KMS policy with foursight roles.
    def update_kms_key_policy(self, key_id: str, sid_pattern: str, additional_roles: list) -> None:
        """
        Updates the specific AWS KMS key policy for the given key_id, whose statement ID (sid)
        matches the given sid_pattern, with the roles contained in the given additional_roles list.
        Will not add if already present. Returns the number of roles actually added.

        :param key_id: KMS key ID.
        :param sid_pattern: Statement ID (sid) pattern to match the specific policy.
        :param additional_roles: List of AWS IAM role ARNs to add to the roles for the specified KMS policy.
        :return: Number of roles from the given additional roles actually added.
        """
        with super().establish_credentials():
            key_policy_json = self.get_kms_key_policy(key_id)
            nadded = self._amend_kms_key_policy(key_policy_json, sid_pattern, additional_roles)
            if nadded > 0:
                yes = yes_or_no(f"Really update KMS policy for {key_id}?")
                if yes:
                    kms = boto3.client("kms")
                    key_policy_string = json.dumps(key_policy_json)
                    kms.put_key_policy(KeyId=key_id, Policy=key_policy_string, PolicyName="default")
            return nadded
