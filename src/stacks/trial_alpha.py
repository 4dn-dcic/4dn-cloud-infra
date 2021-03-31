from src.stack import C4Stack, C4Name, C4Tags, C4Account
from src.parts import network, datastore, ecr, iam, logging, ecs


# Stack metadata
# 'alpha' in this case refers to the first iteration of CGAP Docker on ECS


def c4_alpha_stack_trial_name(name):
    return C4Name(name='c4-{}-trial-ecs'.format(name))


def c4_alpha_stack_trial_tags():
    return C4Tags(env='prod', project='cgap', owner='project')


def c4_alpha_stack_trial_account(aws_account_id=645819926742):
    """ Set to the account ID to deploy in. """
    return C4Account(account_number=aws_account_id)


def c4_alpha_stack_trial_description(stack):
    return 'AWS CloudFormation CGAP {0} template: trial {0} setup for cgap-portal environment using ECS'.format(stack)


def c4_alpha_stack_trial_metadata(name='network'):
    """ Returns the network trial stack name and metadata.
        Allows these to be referenced without compiling the network stack."""
    return (c4_alpha_stack_trial_name(name),
            c4_alpha_stack_trial_description(name))


# Trial-Alpha (ECS) Stacks


def c4_alpha_stack_trial_network():
    """ Network stack for the ECS version of CGAP """
    parts = [network.C4Network]
    name, description = c4_alpha_stack_trial_metadata()
    return C4Stack(
        name=name,
        tags=c4_alpha_stack_trial_tags(),
        account=c4_alpha_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_ecs_stack_trial_datastore():
    """ Datastore stack for the ECS version of CGAP """
    name = 'datastore'
    parts = [datastore.C4Datastore]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=c4_alpha_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_iam():
    """ IAM Configuration for ECS CGAP """
    name = 'iam'
    parts = [iam.C4IAM]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=c4_alpha_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_ecr():
    """ ECR stack for ECS version of CGAP
        depends on IAM above (does that mean it needs both parts?)
    """
    name = 'ecr'
    parts = [iam.C4IAM, ecr.QCContainerRegistry]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=c4_alpha_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_logging():
    """ Implements logging policies for ECS CGAP """
    name = 'logging'
    parts = [logging.C4Logging]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=c4_alpha_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_alpha_stack_trial_ecs():
    """ ECS Stack """
    name = 'ecs'
    parts = [ecs.C4ECSApplication]
    description = c4_alpha_stack_trial_description(name)
    return C4Stack(
        name=c4_alpha_stack_trial_name(name),
        tags=c4_alpha_stack_trial_tags(),
        account=c4_alpha_stack_trial_account(),
        parts=parts,
        description=description,
    )
