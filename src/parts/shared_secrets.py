import json
from troposphere import Template, Output, Ref
from troposphere.secretsmanager import Secret
from ..part import C4Part
from ..exports import C4Exports


class C4SharedSecretsExports(C4Exports):
    """ Ecosystem-wide secrets shared across all envs in an account.
        Currently: DockerHub credentials (one set per account, referenced by every
        appconfig/codebuild deploy that needs to pull a private DockerHub base image).
    """
    EXPORT_DOCKERHUB_CREDENTIALS = 'ExportDockerHubCredentials'

    def __init__(self):
        parameter = 'SharedSecretsStackNameParameter'
        super().__init__(parameter)


class C4SharedSecrets(C4Part):
    """ Ecosystem-scoped stack holding account-wide auxiliary secrets.
        Deployed once per account (sharing=ecosystem → stack name `c4-shared-secrets-main-stack`)
        so multiple per-env appconfig stacks can all reference the same set of credentials. """

    EXPORTS = C4SharedSecretsExports()
    STACK_NAME_TOKEN = 'shared-secrets'
    STACK_TITLE_TOKEN = 'SharedSecrets'
    SHARING = 'ecosystem'

    # AWS Secrets Manager name. Matches the upstream `dhi-registry-credentials:<key>` convention.
    DOCKERHUB_SECRET_LOGICAL_ID = 'DhiRegistryCredentials'
    DOCKERHUB_SECRET_NAME = 'dhi-registry-credentials'
    DOCKERHUB_SECRET_USERNAME_KEY = 'username'
    DOCKERHUB_SECRET_TOKEN_KEY = 'token'

    def build_template(self, template: Template) -> Template:
        dockerhub_secret = self.dockerhub_credentials_secret()
        template.add_resource(dockerhub_secret)
        template.add_output(self.output_dockerhub_credentials(dockerhub_secret))
        return template

    def dockerhub_credentials_secret(self) -> Secret:
        """ DockerHub username + PAT used by CodeBuild when pulling a private base image.
            Referenced as `dhi-registry-credentials:username` / `dhi-registry-credentials:token`.
            Populate post-deploy:
              aws secretsmanager put-secret-value --secret-id dhi-registry-credentials \\
                --secret-string '{"username":"<user>","token":"<dckr_pat_…>"}'
        """
        return Secret(
            self.DOCKERHUB_SECRET_LOGICAL_ID,
            Name=self.DOCKERHUB_SECRET_NAME,
            Description='DockerHub username and Personal Access Token (PAT) for build/runtime use. '
                        'Create the PAT at https://hub.docker.com/settings/security with the '
                        'minimum scope required (typically Read-only).',
            SecretString=json.dumps({
                self.DOCKERHUB_SECRET_USERNAME_KEY: 'PLACEHOLDER',
                self.DOCKERHUB_SECRET_TOKEN_KEY: 'PLACEHOLDER',
            }, indent=2),
            Tags=self.tags.cost_tag_array(),
        )

    def output_dockerhub_credentials(self, secret: Secret) -> Output:
        logical_id = self.name.logical_id(C4SharedSecretsExports.EXPORT_DOCKERHUB_CREDENTIALS)
        return Output(
            logical_id,
            Description='ARN of the shared DockerHub credentials secret (dhi-registry-credentials).',
            Value=Ref(secret),
            Export=self.EXPORTS.export(C4SharedSecretsExports.EXPORT_DOCKERHUB_CREDENTIALS),
        )
