import pytest

from dcicutils.exceptions import InvalidParameterError
from ..base import REGISTERED_STACKS, register_stack_creator, lookup_stack_creator


def test_register_stack_creator_and_lookup_stack_creator():

    class DummyFooImplementationClass:
        pass

    class DummyBarImplementationClass:
        pass

    @register_stack_creator(name='foo', kind='alpha', implementation_class=DummyFooImplementationClass)
    def create_alpha_foo_stack():
        return 'alpha-foo'

    with pytest.raises(InvalidParameterError):  # We've disabled legacy support

        @register_stack_creator(name='foo', kind='legacy', implementation_class=DummyFooImplementationClass)
        def create_legacy_foo_stack():
            return 'legacy-foo'

    @register_stack_creator(name='bar', kind='alpha', implementation_class=DummyBarImplementationClass)
    def create_alpha_bar_stack():
        return 'alpha-bar'

    with pytest.raises(InvalidParameterError):

        @register_stack_creator(name='bar', kind='legacy', implementation_class=DummyBarImplementationClass)
        def create_legacy_bar_stack():
            return 'legacy-bar'

    assert REGISTERED_STACKS == {
        'alpha': {
            'foo': create_alpha_foo_stack,
            'bar': create_alpha_bar_stack,
        },
        # 'legacy': {
        #     'foo': create_legacy_foo_stack,
        #     'bar': create_legacy_bar_stack,
        # },
    }

    with pytest.raises(InvalidParameterError):
        assert lookup_stack_creator(name='foo', kind='legacy', exact=False) == create_legacy_foo_stack
    with pytest.raises(InvalidParameterError):
        assert lookup_stack_creator(name='bar', kind='legacy', exact=False) == create_legacy_bar_stack

    assert lookup_stack_creator(name='foo', kind='alpha', exact=False) == create_alpha_foo_stack
    assert lookup_stack_creator(name='bar', kind='alpha', exact=False) == create_alpha_bar_stack
