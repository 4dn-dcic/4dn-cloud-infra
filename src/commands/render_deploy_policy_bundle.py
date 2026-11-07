""" Renders the deployment permissions (C4IAM.human_deploy_policy_documents) as plain IAM JSON
    for one AWS account and Region, for attaching to an existing IAM Identity Center permission
    set: three customer managed policies plus the permission set's inline policy.

        python -m src.commands.render_deploy_policy_bundle --account-id <id> --region <region> \\
            --permission-set <name> --policy-prefix <prefix> --out <dir> [--check]

    The documents are the generator's, with the account and Region substituted; nothing is added,
    dropped or merged. --check compares an existing bundle instead of writing it. Run it from a
    configured checkout (importing the stack code reads custom/config.json).
"""
import argparse
import json
import os
import re
import sys

from troposphere import encode_to_dict

MANAGED_POLICY_CHARACTERS = 6144     # IAM: customer managed policy, whitespace not counted
INLINE_POLICY_CHARACTERS = 10240     # IAM Identity Center / IAM role: inline policy, whitespace not counted
INLINE_POLICY_BYTES = 32768          # IAM Identity Center: inline policy per permission set
MANIFEST = 'manifest.json'
EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


class UnresolvedValue(ValueError):
    pass


def materialize(value, account_id: str, region: str):
    """ Replaces the CloudFormation intrinsics these policies use (Ref AWS::AccountId,
        Ref AWS::Region, Fn::Join) with concrete strings; any other intrinsic is an error.
    """
    value = encode_to_dict(value)
    if isinstance(value, dict):
        if value == {'Ref': 'AWS::AccountId'}:
            return account_id
        if value == {'Ref': 'AWS::Region'}:
            return region
        if set(value) == {'Fn::Join'}:
            separator, parts = value['Fn::Join']
            return separator.join(materialize(part, account_id, region) for part in parts)
        unresolved = [key for key in value if key == 'Ref' or key.startswith('Fn::')]
        if unresolved:
            raise UnresolvedValue(f'cannot materialize {json.dumps(value)}')
        return {key: materialize(item, account_id, region) for key, item in value.items()}
    if isinstance(value, list):
        return [materialize(item, account_id, region) for item in value]
    return value


def policy_characters(document: dict) -> int:
    """ The size IAM checks against its quotas: characters excluding whitespace. """
    return len(re.sub(r'\s', '', json.dumps(document)))


def _text(data) -> str:
    return json.dumps(data, indent=2) + '\n'


def render_bundle(*, account_id: str, region: str, permission_set: str, policy_prefix: str, out: str) -> dict:
    """ {file name: file text} for the bundle, including its manifest. """
    from ..parts.iam import C4IAM
    documents = C4IAM.human_deploy_policy_documents()
    files, managed = {}, []
    for title, description, document in documents[:3]:
        name = f'{policy_prefix}{title}'
        rendered = materialize(document, account_id, region)
        size = policy_characters(rendered)
        if size > MANAGED_POLICY_CHARACTERS:
            raise ValueError(f'{name} is {size} characters; the managed policy limit is {MANAGED_POLICY_CHARACTERS}')
        files[f'{name}.json'] = _text(rendered)
        managed.append({'name': name, 'path': '/', 'file': f'{name}.json', 'description': description,
                        'characters': size})
    _, _, guardrail = documents[3]
    inline = materialize(guardrail, account_id, region)
    inline_file = f'{permission_set}-inline-policy.json'
    files[inline_file] = _text(inline)
    size = policy_characters(inline)
    if size > INLINE_POLICY_CHARACTERS or len(files[inline_file].encode()) > INLINE_POLICY_BYTES:
        raise ValueError(f'{inline_file} exceeds the permission set inline policy limits')
    files[MANIFEST] = _text({
        'account_id': account_id,
        'region': region,
        'permission_set': permission_set,
        'source': 'src/parts/iam.py C4IAM.human_deploy_policy_documents',
        'generated_by': (f'python -m src.commands.render_deploy_policy_bundle --account-id {account_id}'
                         f' --region {region} --permission-set {permission_set}'
                         f' --policy-prefix {policy_prefix} --out {out}'),
        'customer_managed_policies': managed,
        'aws_managed_policies': [],
        'inline_policy': {'file': inline_file, 'characters': size},
        'limits': {'managed_policy_characters': MANAGED_POLICY_CHARACTERS,
                   'inline_policy_characters': INLINE_POLICY_CHARACTERS,
                   'inline_policy_bytes': INLINE_POLICY_BYTES},
    })
    return files


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(f'error: {message}')
        print('help: python -m src.commands.render_deploy_policy_bundle --account-id <12 digits>'
              ' --region <region> --permission-set <name> --policy-prefix <prefix> --out <dir> [--check]')
        sys.exit(EXIT_USAGE)


def main(argv=None) -> int:
    parser = _Parser(description='Render the deployment policies for one account and Region.')
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--permission-set', required=True, help='existing IAM Identity Center permission set name')
    parser.add_argument('--policy-prefix', required=True, help='prefix for the customer managed policy names')
    parser.add_argument('--out', required=True, help='bundle directory')
    parser.add_argument('--check', action='store_true', help='compare the existing bundle; write nothing')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'\d{12}', args.account_id):
        parser.error('--account-id must be 12 digits')
    if not re.fullmatch(r'[a-z]{2}(-gov)?-[a-z]+-\d', args.region):
        parser.error('--region must be an AWS Region name such as us-east-1')
    if not re.fullmatch(r'[\w+=,.@-]{1,32}', args.permission_set):
        parser.error('--permission-set must be a permission set name')
    if not re.fullmatch(r'[A-Za-z0-9]{1,32}', args.policy_prefix):
        parser.error('--policy-prefix must be alphanumeric')
    try:
        files = render_bundle(account_id=args.account_id, region=args.region,
                              permission_set=args.permission_set, policy_prefix=args.policy_prefix,
                              out=args.out)
    except ValueError as e:
        print(f'error: {e}')
        return EXIT_ERROR
    rows, stale = [], 0
    for name, text in files.items():
        path = os.path.join(args.out, name)
        current = open(path).read() if os.path.exists(path) else None
        if current == text:
            status = 'unchanged'
        elif args.check:
            status, stale = ('missing' if current is None else 'differs'), stale + 1
        else:
            os.makedirs(args.out, exist_ok=True)
            with open(path, 'w') as stream:
                stream.write(text)
            status = 'written'
        rows.append(f'  {name},{status}')
    print(f'bundle: {args.out} ({args.account_id} {args.region} {args.permission_set})')
    print(f'files[{len(rows)}]{{file,status}}:')
    print('\n'.join(rows))
    if stale:
        print(f'help: {stale} file(s) out of date; rerun without --check to regenerate')
        return EXIT_ERROR
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
