from dcicutils.misc_utils import ignorable
from ..part import C4Part, C4Account, C4Tags, C4Name


def test_c4_name():

    raw_name = 'foo-bar'
    expected_stack_name = 'foo-bar-stack'
    expected_logical_id_prefix = 'FooBar'

    name = C4Name(name=raw_name)
    assert name.name == raw_name
    assert name.stack_name == expected_stack_name
    assert name.logical_id_prefix == expected_logical_id_prefix

    raw_name = 'foo-bar'
    expected_stack_name = 'foo-bar-stack'
    expected_logical_id_prefix = 'FOOBar'

    name = C4Name(name=raw_name, title_token='FOOBar')
    assert name.name == raw_name
    assert name.stack_name == expected_stack_name
    assert name.logical_id_prefix == expected_logical_id_prefix


def test_c4_tags():

    default_env = 'test'
    default_project = 'test'
    default_owner = 'test'

    tags = C4Tags()

    assert tags.env == default_env
    assert tags.project == default_project
    assert tags.owner == default_owner

    sample_env = 'foo-env'
    sample_project = 'foo-project'
    sample_owner = 'foo-owner'

    tags = C4Tags(env=sample_env, project=sample_project, owner=sample_owner)

    assert tags.env == sample_env
    assert tags.project == sample_project
    assert tags.owner == sample_owner




def test_c4_account():

    sample_account_number = "123"
    sample_creds_file = "no_such_file.sh"

    account = C4Account(account_number=sample_account_number, creds_file=sample_creds_file)

    assert account.account_number == sample_account_number
    assert account.creds_file == sample_creds_file


# def test_c4_part():
#
#     sample_name = C4Name('sample-part')
#     sample_tags = C4Tags()
#     sample_account = C4Account(account_number='123', creds_file='no_such_file.sh')
#     part = C4Part(name=sample_name, tags=sample_tags, account=sample_account)
#
#     assert part.name == sample_name
#     assert part.tags == sample_tags
#     assert part.account == sample_account
#
#
# def test_c4_part_trim_name():
#
#     # NOTE: It might be nice to make the trimming case-insensitive, but probably it doesn't matter.
#     #       This mostly only comes up because of using the title part of something else that will
#     #       have started with the same data.
#
#     part = C4Part(name=C4Name('sample-part'),
#                   tags=C4Tags(),
#                   account=C4Account(account_number='123',
#                                     creds_file='no_such_file.sh'))
#
#     assert part.trim_name("Stuff") == "Stuff"
#     assert part.trim_name("MoreStuff") == "MoreStuff"
#     assert part.trim_name("SamplePartStuff") == "Stuff"
#     assert part.trim_name("SAMPLEPartStuff") == "SAMPLEPartStuff"  # See note above
#
#     part = C4Part(name=C4Name('foo-part', title_token='FOOPart'),
#                   tags=C4Tags(),
#                   account=C4Account(account_number='123',
#                                     creds_file='no_such_file.sh'))
#
#     assert part.trim_name("Stuff") == "Stuff"
#     assert part.trim_name("MoreStuff") == "MoreStuff"
#     assert part.trim_name("FOOPartStuff") == "Stuff"
#     assert part.trim_name("FooPartStuff") == "FooPartStuff"  # See note above
