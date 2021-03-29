from src.stack import QCStack, QCName, QCTags, QCAccount
from src.parts import network, datastore, ecr, ecs, iam


# Stack metadata


def c4_ecs_stack_trial_name(name):
    return QCName(name='c4-{}-trial-ecs'.format(name))


def c4_ecs_stack_trial_tags():
    return QCTags(env='prod', project='cgap', owner='project')


def c4_ecs_stack_trial_account(aws_account_id=645819926742):
    """ Set to the account ID to deploy in. """
    return QCAccount(account_number=aws_account_id)


def c4_ecs_stack_trial_description(stack):
    return 'AWS CloudFormation CGAP {0} template: trial {0} setup for cgap-portal environment using ECS'.format(stack)


def c4_stack_trial_network_metadata():
    """ Returns the network trial stack name and metadata.
        Allows these to be referenced without compiling the network stack."""
    name = 'network'
    return (c4_ecs_stack_trial_name(name),
            c4_ecs_stack_trial_description(name))


# Trial-ECS Stacks


def c4_ecs_stack_trial_network():
    parts = [network.QCNetwork]
    name, description = c4_stack_trial_network_metadata()
    return QCStack(
        name=name,
        tags=c4_ecs_stack_trial_tags(),
        account=c4_ecs_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_stack_trial_datastore():
    name = 'datastore'
    parts = [datastore.QCDatastore]
    description = c4_ecs_stack_trial_description(name)
    return QCStack(
        name=c4_ecs_stack_trial_name(name),
        tags=c4_ecs_stack_trial_tags(),
        account=c4_ecs_stack_trial_account(),
        parts=parts,
        description=description,
    )


def stack_trial_ecr():
    name = 'ecr'
    parts = [ecr.QCContainerRegistry]
    description = c4_ecs_stack_trial_description(name)
    return QCStack(
        name=c4_ecs_stack_trial_name(name),
        tags=c4_ecs_stack_trial_tags(),
        account=c4_ecs_stack_trial_account(),
        parts=parts,
        description=description,
    )
