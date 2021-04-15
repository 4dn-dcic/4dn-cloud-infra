from src.stack import C4Stack, C4Name, C4Tags, C4Account, C4FoursightCGAPStack
from src.parts import network, datastore, ecr, beanstalk


# Helper methods for construction of trial stacks


def c4_stack_trial_name(name):
    return C4Name(name='c4-{}-trial'.format(name))
    # logical_id_prefix -> C4{Name}Trial
    # stack_name -> c4-{name}-trial-stack


def c4_stack_trial_tags():
    return C4Tags(env='dev', project='cgap', owner='project')


def c4_stack_trial_account():
    return C4Account(account_number='645819926742')


def c4_stack_trial_description(stack):
    return 'AWS CloudFormation CGAP {0} template: trial {0} setup for cgap-portal environment'.format(stack)


def c4_stack_trial_network_metadata():
    """ Returns the network trial stack name and metadata.
        Allows these to be referenced without compiling the network stack."""
    name = 'network'
    return (c4_stack_trial_name(name),
            c4_stack_trial_description(name))


# Trial Stacks


def c4_stack_trial_network():
    parts = [network.C4Network]
    name, description = c4_stack_trial_network_metadata()
    return C4Stack(
        name=name,
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_stack_trial_datastore():
    name = 'datastore'
    parts = [datastore.C4Datastore]
    description = c4_stack_trial_description(name)
    return C4Stack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_stack_trial_beanstalk_meta():
    short_name = 'beanstalk'
    name = c4_stack_trial_name(short_name)
    description = c4_stack_trial_description(short_name)
    return name, description


def c4_stack_trial_beanstalk():
    name, description = c4_stack_trial_beanstalk_meta()
    parts = [beanstalk.C4Beanstalk]
    return C4Stack(
        name=name,
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        parts=parts,
        description=description,
    )


def c4_stack_trial_foursight_cgap():
    name = 'foursight'
    description = c4_stack_trial_description(name)
    return C4FoursightCGAPStack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        description=description,
    )


def stack_trial_ecr():
    name = 'ecr'
    parts = [ecr.C4ContainerRegistry]
    description = c4_stack_trial_description(name)
    return C4Stack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=c4_stack_trial_account(),
        parts=parts,
        description=description,
    )
