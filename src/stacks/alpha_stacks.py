from ..base import register_stack_creator, registered_stack_class
from ..parts import (
    network, datastore, ecr, iam, logging, ecs, fourfront_ecs,
    appconfig, datastore_slim, sentieon, jupyterhub, fourfront_ecs_blue_green
)
from ..stack import (
    C4Stack, C4Tags, C4Account, C4Part, BaseC4FoursightStack,
    C4FoursightCGAPStack, C4FoursightFourfrontStack
)


# Stack metadata
# 'alpha' in this case refers to the first iteration of CGAP Docker on ECS
def _c4_stack_name(name, kind):
    """ This function determines stack names and is shared by CGAP/FF. """
    if isinstance(name, str):
        part = registered_stack_class(name, kind=kind)
    else:
        part = name
    assert issubclass(part, C4Part) or issubclass(part, BaseC4FoursightStack), (
        f"The part {part} is not a C4Part of foursight stack."
    )
    # e.g., if name='network, result will be c4-network-trial-alpha
    # return C4Name(name=f'{COMMON_STACK_PREFIX}{name}-trial-alpha')
    return part.suggest_stack_name(name=name)


def c4_alpha_stack_name(name):
    return _c4_stack_name(name, kind='alpha')


def c4_4dn_stack_name(name):
    return _c4_stack_name(name, kind='4dn')


def c4_alpha_stack_tags():
    """ Tag resources with Alpha (CGAP) tag """
    return C4Tags(env='prod', project='cgap', owner='project')


def c4_4dn_stack_tags():
    """ Tag resources with 4DN tag. """
    return C4Tags(env='prod', project='4dn', owner='project')


def c4_alpha_stack_description(stack):
    return f"AWS CloudFormation Alpha {stack} template, for use in an ECS-based Standalone " \
           f"(CGAP or generic) environment."


def c4_4dn_stack_description(stack):
    return f"AWS CloudFormation 4DN {stack} template, for use in an ECS-based 4DN environment."


def c4_alpha_stack_metadata(name):  # was name='network'
    """ Returns the network trial stack name and metadata.
        Allows these to be referenced without compiling the network stack."""
    if isinstance(name, str):
        part = registered_stack_class(name, kind='alpha')
    else:
        part = name
    assert issubclass(part, C4Part) or issubclass(part, BaseC4FoursightStack), (
        f"The part {part} is not a C4Part of foursight stack."
    )
    return (c4_alpha_stack_name(name),
            c4_alpha_stack_description(name))


def create_c4_alpha_stack(*, name: str, account: C4Account):
    part = registered_stack_class(name, kind='alpha')
    return C4Stack(
        name=c4_alpha_stack_name(name),
        tags=c4_alpha_stack_tags(),
        account=account,
        parts=[part],
        description=c4_alpha_stack_description(name),
    )


def create_c4_4dn_stack(*, name: str, account: C4Account):
    part = registered_stack_class(name, kind='4dn')
    return C4Stack(
        name=c4_4dn_stack_name(part),
        tags=c4_4dn_stack_tags(),
        account=account,
        parts=[part],
        description=c4_4dn_stack_description(name),
    )


def create_c4_alpha_foursight_stack(*, name, account: C4Account):
    foursight_class = registered_stack_class(name, kind='alpha')
    return foursight_class(
        name=c4_alpha_stack_name(name),
        tags=c4_alpha_stack_tags(),
        account=account,
        description=c4_alpha_stack_description(name),
    )


def create_c4_4dn_foursight_stack(*, name, account: C4Account):
    foursight_class = registered_stack_class(name, kind='4dn')
    return foursight_class(
        name=c4_4dn_stack_name(name),
        tags=c4_4dn_stack_tags(),
        account=account,
        description=c4_4dn_stack_description(name),
    )


# Trial-Alpha (ECS) Stacks
@register_stack_creator(name='appconfig', kind='4dn', implementation_class=appconfig.C4AppConfig)
def c4_4dn_stack_trial_appconfig(account: C4Account):
    """ Appconfig stack for the ECS version of Fourfront (just GAC) """
    return create_c4_4dn_stack(name='appconfig', account=account)


@register_stack_creator(name='network', kind='alpha', implementation_class=network.C4Network)
def c4_alpha_stack_network(account: C4Account):
    """ Network stack for the ECS version of CGAP """
    return create_c4_alpha_stack(name='network', account=account)


@register_stack_creator(name='datastore', kind='alpha', implementation_class=datastore.C4Datastore)
def c4_ecs_stack_datastore(account: C4Account):
    """ Datastore stack for the ECS version of CGAP """
    return create_c4_alpha_stack(name='datastore', account=account)


@register_stack_creator(name='iam', kind='alpha', implementation_class=iam.C4IAM)
def c4_alpha_stack_iam(account: C4Account):
    """ IAM Configuration for ECS CGAP """
    return create_c4_alpha_stack(name='iam', account=account)


@register_stack_creator(name='ecr', kind='alpha', implementation_class=ecr.C4ContainerRegistry)
def c4_alpha_stack_ecr(account: C4Account):
    """ ECR stack for ECS version of CGAP
        depends on IAM above (does that mean it needs both parts?)
    """
    return create_c4_alpha_stack(name='ecr', account=account)


@register_stack_creator(name='logging', kind='alpha', implementation_class=logging.C4Logging)
def c4_alpha_stack_logging(account: C4Account):
    """ Implements logging policies for ECS CGAP """
    return create_c4_alpha_stack(name='logging', account=account)


@register_stack_creator(name='ecs', kind='alpha', implementation_class=ecs.C4ECSApplication)
def c4_alpha_stack_ecs(account: C4Account):
    """ ECS Stack """
    return create_c4_alpha_stack(name='ecs', account=account)


@register_stack_creator(name='fourfront_ecs', kind='4dn',
                        implementation_class=fourfront_ecs.FourfrontECSApplication)
def c4_alpha_stack_fourfront_ecs_standalone(account: C4Account):
    """ ECS Stack for a standalone fourfront environment. """
    return create_c4_4dn_stack(name='fourfront_ecs', account=account)


@register_stack_creator(name='fourfront_ecs_blue_green', kind='4dn',
                        implementation_class=fourfront_ecs_blue_green.FourfrontECSBlueGreen)
def c4_alpha_stack_fourfront_ecs_blue_green(account: C4Account):
    """ ECS Stack for a blue/green fourfront environment. """
    return create_c4_4dn_stack(name='fourfront_ecs_blue_green', account=account)


@register_stack_creator(name='datastore_slim', kind='4dn',
                        implementation_class=datastore_slim.C4DatastoreSlim)
def c4_alpha_stack_datastore_slim(account: C4Account):
    """ Slim datastore stack, intended for use with a fourfront environment.
        Assumes existing S3 resources, but creates new RDS and ES resources.
    """
    return create_c4_4dn_stack(name='datastore_slim', account=account)


@register_stack_creator(name='sentieon', kind='alpha', implementation_class=sentieon.C4SentieonSupport)
def c4_alpha_stack_sentieon(account: C4Account):
    """ Sentieon stack, used for spinning up a Sentieon license server for the account. """
    return create_c4_alpha_stack(name='sentieon', account=account)


@register_stack_creator(name='jupyterhub', kind='alpha', implementation_class=jupyterhub.C4JupyterHubSupport)
def c4_alpha_stack_jupyterhub(account: C4Account):
    """ Sentieon stack, used for spinning up a Jupyterhub server for the account. """
    return create_c4_alpha_stack(name='jupyterhub', account=account)


@register_stack_creator(name='foursight', kind='alpha', implementation_class=C4FoursightCGAPStack)
def c4_alpha_stack_foursight_cgap(account: C4Account):
    """ Foursight (prod) stack for cgap - note that either stage can be deployed """
    return create_c4_alpha_foursight_stack(name='foursight', account=account)


@register_stack_creator(name='foursight-production', kind='4dn', implementation_class=C4FoursightFourfrontStack)
def c4_alpha_stack_foursight_fourfront(account: C4Account):
    """ Foursight (prod) stack for fourfront """
    return create_c4_4dn_foursight_stack(name='foursight-production', account=account)


@register_stack_creator(name='foursight-development', kind='4dn', implementation_class=C4FoursightFourfrontStack)
def c4_alpha_stack_foursight_fourfront(account: C4Account):
    """ Foursight (dev) stack for fourfront """
    return create_c4_4dn_foursight_stack(name='foursight-development', account=account)
