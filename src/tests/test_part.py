from ..part import camelize
from dcicutils.misc_utils import snake_case_to_camel_case


def test_camelize():
    data = [
        ("foo", "Foo"),
        ("foo", "Foo"),
        ("-foo-", "Foo"),
        ("foo-bar", "FooBar"),
        ("foo123-bar", "Foo123Bar"),
        ("foo_bar-baz", "Foo_barBaz", "Foo_BarBaz"),
        ("-foo_bar-baz--", "Foo_barBaz", "Foo_BarBaz"),
    ]
    for datum in data:
        (input, output, output2) = (datum + (None, None, None))[0:3]
        result1 = camelize(input)
        result2 = snake_case_to_camel_case(input, separator='-')
        assert result1 == output or result1 == output2
        assert result2 == output or result2 == output2
