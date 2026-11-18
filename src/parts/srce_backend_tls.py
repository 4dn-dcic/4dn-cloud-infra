import re

from ..base import ConfigManager
from ..constants import Settings


class SRCEBackendTLSMixin:
    """
    Backend (ALB -> portal) TLS for the SRCE ECS stacks (standalone and blue/green), resolved from config.

    The hooks it drives live on C4ECSApplication (backend_tls_enabled(), with_backend_tls(),
    portal_container_port() and the target group builder), where they are off, so no other stack can
    reach this setting. Only the SMaHT portal image implements the nginx TLS contract, so only SMaHT
    may enable it.

    Resolution, given ecs.backend_tls (strict boolean or unset), ecs.backend_tls_secret_arn and
    ecs.lb_certificate_arn:

    * false: off. This is the explicit compatibility/rollback switch: the ALB -> task hop stays HTTP
      while a configured frontend certificate still gives browsers HTTPS and the HTTP:80 redirect.
    * true: on. The secret ARN is required, and so is the certificate (except in the closed bootstrap
      stage, which has no listeners); a missing input is an error, never a silent HTTP backend.
    * unset: on when the secret and the certificate are both configured. A secret without a
      certificate is an error rather than a quiet HTTP backend; in the closed bootstrap stage the
      secret alone selects TLS, so leaving the stage by adding the certificate keeps the same
      (HTTPS) target group instead of swapping it. No secret: the legacy render, unchanged.

    Nothing here falls back at runtime: a task whose certificate is missing or invalid fails to start.
    """
    BACKEND_TLS_APP_KIND = 'smaht'

    # Complete Secrets Manager ARN with AWS's random 6-character suffix and nothing after it (in
    # particular no ':JSON_KEY:stage:version' selector -- the selectors are added per key here).
    _SECRET_ARN = re.compile(
        r'^arn:aws(?:-[a-z]+)*:secretsmanager:[a-z]{2}(?:-[a-z]+)+-\d:\d{12}:secret:'
        r'[A-Za-z0-9/_+=.@-]+-[A-Za-z0-9]{6}$')

    def backend_tls_setting(self):
        """ ecs.backend_tls parsed strictly: None (unset), True or False; anything else raises. """
        value = ConfigManager.get_config_setting(Settings.ECS_BACKEND_TLS, default=None)
        if value is None or isinstance(value, bool):
            return value
        raise ValueError(f'{Settings.ECS_BACKEND_TLS} must be true or false, not {value!r}')

    def backend_tls_secret_arn(self):
        """ ecs.backend_tls_secret_arn, validated as a complete secret ARN, or None when unset. """
        value = ConfigManager.get_config_setting(Settings.ECS_BACKEND_TLS_SECRET_ARN, default=None)
        if value is None:
            return None
        if not isinstance(value, str) or not self._SECRET_ARN.match(value.strip()):
            raise ValueError(
                f'{Settings.ECS_BACKEND_TLS_SECRET_ARN} must be the complete Secrets Manager secret ARN, ending in'
                f' the secret name and its 6-character suffix with no JSON-key selector, not {value!r}')
        return value.strip()

    def backend_tls_enabled(self) -> bool:
        setting = self.backend_tls_setting()
        secret_arn = self.backend_tls_secret_arn()
        if setting is False:
            return False
        if setting is None and not secret_arn:
            return False  # nothing configured: the legacy render
        app_kind = ConfigManager.get_config_setting(Settings.APP_KIND)
        closed = self.bootstrap_closed()
        problems = []
        if app_kind != self.BACKEND_TLS_APP_KIND:
            problems.append(f'it is supported only for app.kind {self.BACKEND_TLS_APP_KIND!r}, not {app_kind!r}')
        if not secret_arn:
            problems.append(f'{Settings.ECS_BACKEND_TLS_SECRET_ARN} is not set')
        if not self.lb_certificate_arn() and not closed:
            problems.append(f'{Settings.ECS_LB_CERTIFICATE_ARN} is not set')
        if problems:
            how = (f'{Settings.ECS_BACKEND_TLS} is true' if setting
                   else f'{Settings.ECS_BACKEND_TLS_SECRET_ARN} is set (so backend TLS defaults on)')
            raise ValueError(f'Backend TLS: {how}, but ' + '; '.join(problems)
                             + f'. Supply the missing input(s), or set {Settings.ECS_BACKEND_TLS} to false'
                               f' for the HTTP backend.')
        return True
