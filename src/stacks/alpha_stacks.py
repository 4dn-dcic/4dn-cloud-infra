from ..base import register_stack_creator, COMMON_STACK_PREFIX, COMMON_STACK_PREFIX_CAMEL_CASE
from ..parts import network, datastore, ecr, iam, logging, ecs  # , appconfig
from ..stack import C4Stack, C4Name, C4Tags, C4Account, C4FoursightCGAPStack


# Stack metadata
# 'alpha' in this case refers to the first iteration of CGAP Docker on ECS

def c4_alpha_stack_name(name, camel_case_name=None):
    # e.g., if name='network, result will be c4-network-trial-alpha
    # return C4Name(name=f'{COMMON_STACK_PREFIX}{name}-trial-alpha')

    # Experimentally return something simpler...
    return C4Name(name=f'{COMMON_STACK_PREFIX}{name}',
                  title_token=(f'{COMMON_STACK_PREFIX_CAMEL_CASE}{camel_case_name}'
                               if camel_case_name else None))


def c4_alpha_stack_tags():
    return C4Tags(env='prod', project='cgap', owner='project')


def c4_alpha_stack_description(stack):
    return f"AWS CloudFormation CGAP {stack} template, for use in an ECS-based CGAP environment."


def c4_alpha_stack_metadata(name='network'):
    """ Returns the network trial stack name and metadata.
        Allows these to be referenced without compiling the network stack."""
    return (c4_alpha_stack_name(name),
            c4_alpha_stack_description(name))


def create_c4_alpha_stack(*, name, title_token, account, parts):
    return C4Stack(
        name=c4_alpha_stack_name(name, camel_case_name=title_token),
        tags=c4_alpha_stack_tags(),
        account=account,
        parts=parts,
        description=c4_alpha_stack_description(title_token),
    )


def create_c4_alpha_foursight_stack(*, name, title_token, account, foursight_class):
    return foursight_class(
        name=c4_alpha_stack_name(name, camel_case_name=title_token),
        tags=c4_alpha_stack_tags(),
        account=account,
        description=c4_alpha_stack_description(title_token),
    )


# Trial-Alpha (ECS) Stacks

# @register_stack_creator(name='appconfig', kind='alpha')
# def c4_alpha_stack_trial_appconfig(account: C4Account):
#     """ Network stack for the ECS version of CGAP """
#     return create_c4_alpha_stack(name='appconfig', title_token='AppConfig', account=account,
#                                  parts=[appconfig.C4AppConfig])


@register_stack_creator(name='network', kind='alpha')
def c4_alpha_stack_network(account: C4Account):
    """ Network stack for the ECS version of CGAP """
    return create_c4_alpha_stack(name='network', title_token='Network', account=account,
                                 parts=[network.C4Network])


@register_stack_creator(name='datastore', kind='alpha')
def c4_ecs_stack_datastore(account: C4Account):
    """ Datastore stack for the ECS version of CGAP """
    return create_c4_alpha_stack(name='datastore', title_token='Datastore', account=account,
                                 parts=[datastore.C4Datastore])


@register_stack_creator(name='iam', kind='alpha')
def c4_alpha_stack_iam(account: C4Account):
    """ IAM Configuration for ECS CGAP """
    return create_c4_alpha_stack(name='iam', title_token='IAM', account=account,
                                 parts=[iam.C4IAM])


@register_stack_creator(name='ecr', kind='alpha')
def c4_alpha_stack_ecr(account: C4Account):
    """ ECR stack for ECS version of CGAP
        depends on IAM above (does that mean it needs both parts?)
    """
    return create_c4_alpha_stack(name='ecr', title_token='ECR', account=account,
                                 parts=[ecr.C4ContainerRegistry])


@register_stack_creator(name='logging', kind='alpha')
def c4_alpha_stack_logging(account: C4Account):
    """ Implements logging policies for ECS CGAP """
    return create_c4_alpha_stack(name='logging', title_token='Logging', account=account,
                                 parts=[logging.C4Logging])


@register_stack_creator(name='ecs', kind='alpha')
def c4_alpha_stack_ecs(account: C4Account):
    """ ECS Stack """
    return create_c4_alpha_stack(name='ecs', title_token='ECS', account=account,
                                 parts=[ecs.C4ECSApplication])


@register_stack_creator(name='foursight', kind='alpha')
def c4_alpha_stack_foursight_cgap(account: C4Account):
    """ Foursight stack """
    return create_c4_alpha_foursight_stack(name='foursight', title_token='Foursight', account=account,
                                           foursight_class=C4FoursightCGAPStack)
