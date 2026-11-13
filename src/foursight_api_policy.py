""" Opt-in source-CIDR restriction for the Foursight REST API (``foursight.api_source_cidrs``).

    Foursight is packaged by chalice, so the restriction is an API Gateway *resource policy* that
    chalice embeds in the generated API definition (``x-amazon-apigateway-policy``) when the stage
    config names an ``api_gateway_policy_file``. Because the policy is part of the API definition,
    the SAM transform's hash-named ``AWS::ApiGateway::Deployment`` changes whenever the policy is
    added, changed or removed, and both stages chalice/SAM create (``api`` and SAM's ``Stage``) move
    to that new deployment. A policy set on the API after deployment would not reach a stage until
    something redeployed it.
"""
import ipaddress
import json
import os

from .base import ConfigManager
from .constants import Settings

#: Written next to ``.chalice/config.json``; chalice resolves the stage's policy file there.
POLICY_FILE_NAME = 'foursight-api-policy.json'

# aws:SourceIp sees the public address a request arrives from, so a private, loopback or link-local
# range can never match it: configuring one would silently deny every caller (or is a sign that
# aws:VpcSourceIp was meant, which this option does not implement).
_NON_PUBLIC_NETWORKS = [ipaddress.ip_network(n) for n in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', '127.0.0.0/8', '169.254.0.0/16',
    'fc00::/7', 'fe80::/10', '::1/128',
)]


class FoursightApiSourceCidrsError(ValueError):
    pass


def _entries(value):
    """ Accept a list, its Python repr / JSON form (how config.json lists reach us, see CLN-10 in
        src/base.py), or a comma-separated string. """
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value]
    text = str(value).strip()
    if text.startswith('['):
        try:
            return [str(v).strip() for v in json.loads(text.replace("'", '"'))]
        except json.JSONDecodeError:
            raise FoursightApiSourceCidrsError(
                f"{Settings.FOURSIGHT_API_SOURCE_CIDRS} is not a valid list of CIDRs: {text!r}")
    return [s.strip() for s in text.split(',')]


def parse_source_cidrs(value):
    """ Validate a configured ``foursight.api_source_cidrs`` value.

        Returns ``None`` when the setting is absent (no restriction, unchanged behavior), otherwise a
        de-duplicated list of normalized IPv4/IPv6 CIDRs. Raises on anything that is empty, malformed,
        has host bits set, allows every address, or can never be a public source address.
    """
    if value is None:
        return None
    key = Settings.FOURSIGHT_API_SOURCE_CIDRS
    entries = _entries(value)
    if not entries or any(not e for e in entries):
        raise FoursightApiSourceCidrsError(
            f"{key} is set but has an empty entry: {value!r}. List at least one CIDR, or remove the"
            f" setting to leave the Foursight API unrestricted.")
    cidrs = []
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=True)
        except ValueError as e:
            raise FoursightApiSourceCidrsError(f"{key} entry {entry!r} is not a valid CIDR: {e}")
        if network.prefixlen == 0:
            raise FoursightApiSourceCidrsError(
                f"{key} entry {entry!r} matches every address; remove the setting instead.")
        if (network.is_multicast or network.is_unspecified
                or any(network.version == n.version and network.overlaps(n) for n in _NON_PUBLIC_NETWORKS)):
            raise FoursightApiSourceCidrsError(
                f"{key} entry {entry!r} is not a public address range; API Gateway compares"
                f" aws:SourceIp with the caller's public egress address, so it could never match.")
        if str(network) not in cidrs:
            cidrs.append(str(network))
    return cidrs


def configured_source_cidrs():
    """ The validated setting from the sourced configuration (call inside
        ``ConfigManager.validate_and_source_configuration()``). """
    return parse_source_cidrs(ConfigManager.get_config_setting(Settings.FOURSIGHT_API_SOURCE_CIDRS,
                                                               default=None))


def source_cidr_policy(cidrs):
    """ The standard API Gateway SourceIp resource policy: allow invoke, and explicitly deny any
        request whose source address is outside ``cidrs``. ``execute-api:/*`` covers every stage,
        method and path of this API, so no stage is left without the restriction. """
    resource = 'execute-api:/*'
    return {
        'Version': '2012-10-17',
        'Statement': [
            {'Sid': 'AllowInvoke', 'Effect': 'Allow', 'Principal': '*',
             'Action': 'execute-api:Invoke', 'Resource': resource},
            {'Sid': 'DenyOutsideAllowedSourceCidrs', 'Effect': 'Deny', 'Principal': '*',
             'Action': 'execute-api:Invoke', 'Resource': resource,
             'Condition': {'NotIpAddress': {'aws:SourceIp': list(cidrs)}}},
        ],
    }


def apply_to_chalice_config(config_base, chalice_dir, cidrs):
    """ Point every stage of ``config_base`` at the generated policy file and write it, or -- when
        ``cidrs`` is None -- undo exactly that and leave the config as it was.

        A stage that already names a *different* policy file (or a private endpoint, whose default
        policy chalice generates) is never overwritten: combining the two is a decision for whoever
        owns that policy, so this raises instead.
    """
    path = os.path.join(chalice_dir, POLICY_FILE_NAME)
    for stage_name, stage in config_base['stages'].items():
        existing = stage.get('api_gateway_policy_file')
        if existing not in (None, POLICY_FILE_NAME) or (
                cidrs is not None and stage.get('api_gateway_endpoint_type') == 'PRIVATE'):
            raise FoursightApiSourceCidrsError(
                f"Chalice stage {stage_name!r} already has its own API policy"
                f" ({existing or 'PRIVATE endpoint default'}); {Settings.FOURSIGHT_API_SOURCE_CIDRS}"
                f" will not replace it.")
        if cidrs is None:
            stage.pop('api_gateway_policy_file', None)
        else:
            stage['api_gateway_policy_file'] = POLICY_FILE_NAME
    if cidrs is None:
        if os.path.exists(path):
            os.remove(path)  # our own generated file; never left behind to be mistaken for config
        return None
    with open(path, 'w') as f:
        json.dump(source_cidr_policy(cidrs), f, indent=2)
    return path
