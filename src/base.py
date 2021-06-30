from dcicutils.misc_utils import decorator
from .exceptions import CLIException


REGISTERED_STACKS = {}

STACK_KINDS = ['legacy', 'alpha']


@decorator()
def register_stack_creator(*, name, kind):
    if kind not in STACK_KINDS:
        raise SyntaxError("A stack kind must be one of %s." % " or ".join(STACK_KINDS))

    def register_stack_creation_function(fn):
        subregistry = REGISTERED_STACKS.get(kind)
        if not subregistry:
            REGISTERED_STACKS[kind] = subregistry = {}
        subregistry[name] = fn
        return fn

    return register_stack_creation_function


def lookup_stack_creator(name, kind, exact=False):
    if kind not in STACK_KINDS:
        raise ValueError("A stack kind must be one of %s." % " or ".join(STACK_KINDS))
    for stack_short_name, stack_creator in REGISTERED_STACKS[kind].items():
        if exact and name == stack_short_name:
            return stack_creator
        elif not exact and stack_short_name in name:
            return stack_creator
    raise CLIException("A %s stack %s %r was not found." % (kind, "called" if exact else "whose name contains", name))
