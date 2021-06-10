from src.stack import C4Stack, C4Name, C4Tags, C4Account, C4FoursightCGAPStack
from src.parts import network, datastore, ecr, beanstalk, tibanna

# Helper methods for construction of trial stacks


def c4_stack_trial_name(name):
    return C4Name(name='c4-{}-trial'.format(name))
    # logical_id_prefix -> C4{Name}Trial
    # stack_name -> c4-{name}-trial-stack


def c4_stack_trial_tags():
    return C4Tags(env='dev', project='cgap', owner='project')


def c4_stack_trial_description(stack):
    return 'AWS CloudFormation CGAP {0} template: trial {0} setup for cgap-portal environment'.format(stack)


def c4_stack_trial_network_metadata():
    """ Returns the network trial stack name and metadata.
        Allows these to be referenced without compiling the network stack."""
    name = 'network'
    return (c4_stack_trial_name(name),
            c4_stack_trial_description(name))


# Trial Stacks


def c4_stack_trial_network(account: C4Account):
    parts = [network.C4Network]
    name, description = c4_stack_trial_network_metadata()
    return C4Stack(
        name=name,
        tags=c4_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_stack_trial_datastore(account: C4Account):
    name = 'datastore'
    parts = [datastore.C4Datastore]
    description = c4_stack_trial_description(name)
    return C4Stack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_stack_trial_beanstalk_meta():
    short_name = 'beanstalk'
    name = c4_stack_trial_name(short_name)
    description = c4_stack_trial_description(short_name)
    return name, description


def c4_stack_trial_beanstalk(account: C4Account):
    name, description = c4_stack_trial_beanstalk_meta()
    parts = [beanstalk.C4Beanstalk]
    return C4Stack(
        name=name,
        tags=c4_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def c4_stack_trial_foursight_cgap(account: C4Account):
    name = 'foursight'
    description = c4_stack_trial_description(name)
    return C4FoursightCGAPStack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=account,
        description=description,
    )


def c4_stack_trial_tibanna(account: C4Account):
    name = 'tibanna'
    description = 'tibanna trial stack'
    parts = [tibanna.C4Tibanna]
    return C4Stack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )


def stack_trial_ecr(account: C4Account):
    name = 'ecr'
    parts = [ecr.C4ContainerRegistry]
    description = c4_stack_trial_description(name)
    return C4Stack(
        name=c4_stack_trial_name(name),
        tags=c4_stack_trial_tags(),
        account=account,
        parts=parts,
        description=description,
    )
