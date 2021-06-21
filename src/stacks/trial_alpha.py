from src.stack import C4Stack, C4Name, C4Tags, C4Account, C4FoursightCGAPStack
from src.parts import network, datastore, ecr, iam, logging, ecs, appconfig


# Stack metadata
# 'alpha' in this case refers to the first iteration of CGAP Docker on ECS


def c4_alpha_stack_trial_name(name):
    return C4Name(name='c4-{}-trial-alpha'.format(name))


def c4_alpha_stack_trial_tags():
    return C4Tags(env='prod', project='cgap', owner='project')


def c4_alpha_stack_trial_description(stack):
    return 'AWS CloudFormation CGAP {0} template: trial {0} setup for cgap-portal environment using ECS'.format(stack)


def c4_alpha_stack_trial_metadata(name='network'):
    """ Returns the network trial stack name and metadata.
        Allows these to be referenced without compiling the network stack."""
    return (c4_alpha_stack_trial_name(name),
            c4_alpha_stack_trial_description(name))


# Trial-Alpha (ECS) Stacks

def c4_alpha_stack_trial_appconfig(account: C4Account):
    """ Network stack for the ECS version of CGAP """
    name = 'appconfig'
    parts = [appconfig.C4AppConfig]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_network(account: C4Account):
    """ Network stack for the ECS version of CGAP """
    parts = [network.C4Network]
    name, description = c4_alpha_stack_trial_metadata()
    return C4Stack(
        name=name,
        tags=c4_alpha_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_ecs_stack_trial_datastore(account: C4Account):
    """ Datastore stack for the ECS version of CGAP """
    name = 'datastore'
    parts = [datastore.C4Datastore]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_iam(account: C4Account):
    """ IAM Configuration for ECS CGAP """
    name = 'iam'
    parts = [iam.C4IAM]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_ecr(account: C4Account):
    """ ECR stack for ECS version of CGAP
        depends on IAM above (does that mean it needs both parts?)
    """
    name = 'ecr'
    parts = [ecr.C4ContainerRegistry]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_logging(account: C4Account):
    """ Implements logging policies for ECS CGAP """
    name = 'logging'
    parts = [logging.C4Logging]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_ecs(account: C4Account):
    """ ECS Stack """
    name = 'ecs'
    parts = [ecs.C4ECSApplication]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_foursight_cgap(account: C4Account):
    """ Foursight stack """
    name = 'foursight'
    description = c4_alpha_stack_trial_description(name)
    return C4FoursightCGAPStack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=account,
        description=description,
    )
