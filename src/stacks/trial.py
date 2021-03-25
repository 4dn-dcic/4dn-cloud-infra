from src.stack import QCStack, QCName, QCTags, QCAccount
from src.parts import network, datastore, ecr, beanstalk


def c4_stack_trial_name(name):
    return QCName(name='c4-{}-trial'.format(name))
    # logical_id_prefix -> C4{Name}Trial
    # stack_name -> c4-{name}-trial-stack


def c4_stack_trial_tags():
    return QCTags(env='dev', project='cgap', owner='project')


def c4_stack_trial_account():
    return QCAccount(account_number='645819926742')


def c4_stack_trial_description(stack):
    return 'AWS CloudFormation CGAP {0} template: trial {0} setup for cgap-portal environment'.format(stack)


def c4_stack_trial_network():
    name = 'network'
    parts = [network.QCNetwork]
    description=c4_stack_trial_description(name)
    return QCStack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_stack_trial_datastore():
    name = 'datastore'
    parts = [datastore.QCDatastore]
    description = c4_stack_trial_description(name)
    return QCStack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_stack_trial_beanstalk():
    name = 'beanstalk'
    parts = [beanstalk.QCBeanstalk]
    description=c4_stack_trial_description(name)
    return QCStack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        parts=parts,
        description=description,
    )


def stack_trial_ecr():
    name = 'ecr'
    parts = [ecr.QCContainerRegistry]
    description=c4_stack_trial_description(name)
    return QCStack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        parts=parts,
        description=description,
    )
