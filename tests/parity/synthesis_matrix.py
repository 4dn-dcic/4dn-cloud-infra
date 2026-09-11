"""Self-contained offline synthesis matrix used to prove the fixed stacks did not move.

This module is deliberately free of any dependency on the rest of ``tests/`` (no conftest
fixtures, no repo-local test helpers) so the *same* code can be run against an arbitrary git ref::

    git archive origin/master | tar -x -C /tmp/ref
    cp -r tests/parity /tmp/ref/tests/parity
    cd /tmp/ref && python -m tests.parity.synthesis_matrix baseline.json

That is how ``fixed_stack_baseline.json`` was produced from ``origin/master``: the baseline must
come from the reference code, never from the branch under test, or it would assert its own result.

Nothing here contacts AWS or the network; both are hard-denied below.
"""
import contextlib
import hashlib
import json
import os
import platform
import socket
import sys

# --- deny all network/AWS access for the whole process -----------------------------------------
import botocore.client


def _deny(*args, **kwargs):
    raise AssertionError('parity synthesis must not contact a network or AWS API')


socket.socket.connect = _deny
botocore.client.BaseClient._make_api_call = _deny

import troposphere  # noqa: E402
from troposphere import Template  # noqa: E402
from src import base  # noqa: E402
from src.base import ConfigManager, REGISTERED_STACK_CLASSES  # noqa: E402
from src.part import C4Account, C4Part, C4Tags  # noqa: E402
from src.parts import application_configuration_secrets as _acs  # noqa: E402
import src.stacks.alpha_stacks  # noqa: F401,E402  (importing registers every stack creator)

# The appconfig stack embeds the deployed OpenSearch URL, which it normally resolves by describing
# CloudFormation stacks. Pin it so synthesis is offline and identical on both sides of the compare.
_acs.ApplicationConfigurationSecrets.get_es_url = classmethod(
    lambda cls: 'https://es.parity.invalid:443')

# --- hermetic configuration ---------------------------------------------------------------------
#
# ConfigManager.get_config_setting() reads os.environ inside
# ConfigManager.validate_and_source_configuration(), which sources the config over the ambient
# environment. Any setting the matrix does not pin therefore falls through to whatever the caller's
# shell exports -- and several of them are real credentials (Auth0Client, Auth0Secret,
# S3_ENCRYPT_KEY are read straight into the appconfig GAC secret's SecretString). Two consequences,
# both unacceptable here:
#
#   * the fingerprints stop being a property of the repository. A baseline generated on a developer
#     machine that exports those variables does not match the same code synthesized in CI, which
#     exports none of them, and the whole comparison fails for reasons unrelated to any change.
#   * ambient secret *values* end up inside synthesized templates.
#
# So synthesis runs against exactly the pinned config plus a few process-level variables that are
# not configuration at all. Everything else is unset for the duration.
_PROCESS_ENV_KEYS = ('PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'PYTHONPATH', 'PWD', 'SYSTEMROOT',
                     'VIRTUAL_ENV', 'PYENV_ROOT')


@contextlib.contextmanager
def _pinned_environment():
    saved = dict(os.environ)
    pinned = {key: value
              for key, value in (ConfigManager.singleton()._CACHED_CONFIG or {}).items()
              if value is not None}
    kept = {key: saved[key] for key in _PROCESS_ENV_KEYS if key in saved}
    os.environ.clear()
    os.environ.update(kept)
    os.environ.update(pinned)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


ConfigManager.validate_and_source_configuration = classmethod(lambda cls: _pinned_environment())

# Same reasoning: this reads custom/aws_creds/s3_encrypt_key.txt if a developer happens to have one.
ConfigManager.get_s3_encrypt_key_from_file = classmethod(lambda cls: None)

# Modules that snapshot APP_KIND / APP_DEPLOYMENT at import time and must be re-pointed per variant.
_MODULE_NAMES = [
    'appconfig', 'codebuild', 'datastore', 'datastore_slim', 'ecs', 'ecs_blue_green',
    'fourfront_ecs', 'logging', 'iam', 'ecr', 'network', 'redis', 'sentieon', 'higlass',
    'jupyterhub', 'tibanna', 'srce_network', 'srce_datastore', 'srce_ecs', 'srce_ecs_blue_green',
    'srce_redis', 'srce_sentieon',
]


def _modules():
    found = [base]
    for name in _MODULE_NAMES:
        try:
            found.append(__import__(f'src.parts.{name}', fromlist=['x']))
        except ImportError:
            pass  # module does not exist on this ref
    return found


# Config common to every variant. Deliberately does NOT set any of the settings the retained
# changes are gated on -- ecs.lb_certificate_arn, crowdstrike.enabled, vpc.id -- because the point
# is that a deployment which does not opt in gets exactly the templates it got before.
BASE_CONFIG = {
    'account_number': '123456789012', 'deploying_iam_user': 'arn:aws:iam::123456789012:user/test',
    'identity': 'C4AppConfigTest', 'blue.identity': 'C4AppConfigTestBlue',
    'green.identity': 'C4AppConfigTestGreen', 'GITHUB_PERSONAL_ACCESS_TOKEN': 'offline-test',
    's3.bucket.org': 'testorg', 's3.bucket.ecosystem': 'main',
    'higlass.ssh_key': 'test-key', 'jupyterhub.ssh_key': 'test-key', 'sentieon.ssh_key': 'test-key',
    'fourfront.vpc': 'vpc-0aaaaaaaaaaaaaaa1', 'fourfront.vpc.cidr': '10.10.0.0/16',
    'fourfront.vpc.subnet_a': 'subnet-0aaaaaaaaaaaaaaa1',
    'fourfront.vpc.subnet_b': 'subnet-0aaaaaaaaaaaaaaa2',
    'fourfront.rds.sg': 'sg-0bbbbbbbbbbbbbbb1', 'fourfront.https.sg': 'sg-0aaaaaaaaaaaaaaa1',
}

# (label, app.kind, app.deploy)
VARIANTS = [
    ('cgap-standalone', 'cgap', 'standalone'),
    ('cgap-blue-green', 'cgap', 'blue/green'),
    ('ff-standalone', 'ff', 'standalone'),
    ('ff-blue-green', 'ff', 'blue/green'),
    ('smaht-standalone', 'smaht', 'standalone'),
    ('smaht-blue-green', 'smaht', 'blue/green'),
]

# Stacks whose templates the fresh SMaHT SRCE blue/green deployment is allowed to ADD resources to,
# because it consumes them as shared prerequisites. Additive only: no pre-existing logical id may
# change or disappear. Everything else must be byte-identical.
ADDITIVE_STACKS = {
    'alpha:ecr': 'falcon-sensor ECR repository for the CrowdStrike sidecar image',
    'alpha:appconfig': 'Foursight configuration secret used as the foursight-srce IDENTITY',
    '4dn:appconfig': 'Foursight configuration secret used as the foursight-srce IDENTITY',
}

SECTIONS = ('Parameters', 'Resources', 'Outputs', 'Conditions', 'Mappings')


def canonical(value):
    return json.dumps(value, sort_keys=True, default=str)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def configure(kind, deployment):
    values = dict(BASE_CONFIG)
    values.update({'app.kind': kind, 'app.deploy': deployment,
                   'ENCODED_ENV_NAME': f'{kind}-parity'})
    ConfigManager.singleton()._CACHED_CONFIG = {
        key: (str(val) if val is not None else None) for key, val in values.items()}
    for module in _modules():
        if hasattr(module, 'APP_KIND'):
            module.APP_KIND = kind
        if hasattr(module, 'APP_DEPLOYMENT'):
            module.APP_DEPLOYMENT = deployment


def synthesize(cls):
    part = cls(name=cls.suggest_stack_name(), tags=C4Tags(),
               account=C4Account(account_number='123456789012', creds_file='/dev/null'))
    return part.build_template(Template()).to_dict()


def registered_parts():
    """ {qualified name: part class} for every registered stack that is a synthesizable C4Part. """
    parts = {}
    for kind in ('alpha', '4dn'):
        for name, cls in REGISTERED_STACK_CLASSES.get(kind, {}).items():
            if isinstance(cls, type) and issubclass(cls, C4Part):
                parts[f'{kind}:{name}'] = cls
    return parts


def build_matrix():
    """ {variant: {qualified stack name: fingerprint}}.

        A fingerprint is either ``{'error': <exception text>}`` (some stacks legitimately refuse to
        synthesize in a variant, e.g. blue/green stacks under a standalone deployment -- that
        refusal is itself part of the contract) or ``{'digest': ..., 'sections': {...}}`` carrying
        both the whole-template digest and a per-logical-id digest, so an additive change can be
        distinguished from a mutation.
    """
    matrix = {}
    for label, kind, deployment in VARIANTS:
        configure(kind, deployment)
        per_variant = {}
        for name, cls in sorted(registered_parts().items()):
            try:
                template = synthesize(cls)
            except Exception as error:  # noqa: BLE001 - recorded, not swallowed
                per_variant[name] = {'error': f'{type(error).__name__}: {error}'}
                continue
            per_variant[name] = {
                'digest': digest(template),
                'sections': {section: {key: digest(val)
                                       for key, val in (template.get(section) or {}).items()}
                             for section in SECTIONS},
            }
        matrix[label] = per_variant
    return matrix


BASELINE_PATH = os.path.join(os.path.dirname(__file__), 'fixed_stack_baseline.json')


def environment():
    """ What the fingerprints depend on besides this repository, and is compared.

        Digests are taken over *rendered* CloudFormation, so a troposphere upgrade can change every
        one of them without a single change here. Recording the renderer's version turns that from
        ~100 unreadable digest mismatches into one actionable message (see
        tests/test_fixed_stack_parity.py). Only troposphere is compared: the repo supports several
        Python minors and CI runs a different one from most development environments, and rendering
        is identical across them (verified across 3.10 and 3.11).
    """
    return {'troposphere': troposphere.__version__}


def provenance():
    """ Informational only -- never compared. Helps diagnose an unexpected mismatch. """
    return {'python': '.'.join(platform.python_version_tuple()[:2])}


def load_baseline():
    with open(BASELINE_PATH) as fp:
        return json.load(fp)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else BASELINE_PATH
    baseline = {'environment': environment(), 'generated_under': provenance(),
                'matrix': build_matrix()}
    with open(out, 'w') as fp:
        json.dump(baseline, fp, indent=1, sort_keys=True)
        fp.write('\n')
    print(f"wrote {out}: {len(baseline['matrix'])} variants, "
          f"{len(next(iter(baseline['matrix'].values())))} registered stacks each, "
          f"environment {baseline['environment']}, generated under {baseline['generated_under']}")
