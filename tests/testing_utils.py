import re
from typing import Callable

def rummage_for_print_message(mocked_print, regular_expression: str) -> bool:
    """
    Searches the given print mock for the/a print call whose arguments matches the given regular
    expression, and returns True if it finds (at least) ONE that matches, otherwise returns False.

    :param mocked_print: Mock print object.
    :param regular_expression: Regular expression to look for in mock print values/lines.
    :return: True if at least one match found otherwise False.
    """
    for value in mocked_print.lines:
        if re.search(regular_expression, value, re.IGNORECASE):
            return True
    return False


def rummage_for_print_message_all(mocked_print, regular_expression: str, predicate: Callable) -> bool:
    """
    Searches the given print mock for the/a call whose argument matches the given regular
    expression and returns True iff EVERY match ALSO passes (gets a True return value
    from) the given predicate function with that argument, otherwise returns False.

    :param mocked_print: Mock print object.
    :param regular_expression: Regular expression to look for in mock print output values/lines.
    :param predicate: Regular expression to look for in mock print values/lines.
    :return: True if ALL matched mock print values/lines passes the given predicate test otherwise False.
    """
    for value in mocked_print.lines:
        if re.search(regular_expression, value, re.IGNORECASE):
            if not predicate(value):
                return False
    return True
