"""Default chalice merge template applied to every Foursight stack package.

The default template (``foursight_merge_template.yaml`` at the repo root) sets
``RecursiveLoop: Allow`` on the ``CheckRunner`` function, which intentionally
re-invokes itself to drain the SQS check queue.  Without it, AWS Lambda
recursive loop detection would stop long check-runner chains.
"""

import os

from chalice.package import TemplateDeepMerger, YAMLTemplateSerializer
from dcicutils.misc_utils import PRINT


DEFAULT_FOURSIGHT_MERGE_TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                'foursight_merge_template.yaml')
COMBINED_MERGE_TEMPLATE_NAME = 'merge_template.yaml'


def load_template(path):
    with open(path) as fp:
        return YAMLTemplateSerializer().load_template(fp.read(), path)


def resolve_merge_template(user_merge_template=None, output_dir=None):
    """Return the merge template path to pass to chalice package.

    With no user template, this is the default template.  With a user template, the
    user template is deep-merged over the default (user values win) and the result is
    written to ``<output_dir>/merge_template.yaml``, whose path is returned.
    """
    if not user_merge_template:
        PRINT(f"Using default Foursight merge template: {DEFAULT_FOURSIGHT_MERGE_TEMPLATE}")
        return DEFAULT_FOURSIGHT_MERGE_TEMPLATE
    if not output_dir:
        raise ValueError("An output directory is required to combine a user merge template with the default.")
    merged = TemplateDeepMerger().merge(load_template(user_merge_template),
                                        load_template(DEFAULT_FOURSIGHT_MERGE_TEMPLATE))
    os.makedirs(output_dir, exist_ok=True)
    combined = os.path.abspath(os.path.join(output_dir, COMBINED_MERGE_TEMPLATE_NAME))
    with open(combined, 'w') as fp:
        fp.write(YAMLTemplateSerializer().serialize_template(merged))
    PRINT(f"Using merge template {user_merge_template} combined with default"
          f" {DEFAULT_FOURSIGHT_MERGE_TEMPLATE}: {combined}")
    return combined
