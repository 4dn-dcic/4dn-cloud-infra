from troposphere import Export, Sub, ImportValue


class C4Exports:
    """ Helper class for working with exported resources and their input values.
        Usage: Add globals to inherited class (see src.part.network.C4NetworkExports).
    """
    def __init__(self, reference_param_key):
        self.reference_param_key = reference_param_key
        self.reference_param = '${' + self.reference_param_key + '}'
        self.stack_name_param = '${AWS::StackName}'

    def export(self, resource_id):
        """ Helper method for building the Export field in an Output for a template. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html
        """
        return Export(Sub(
            '{}-{}'.format(self.stack_name_param, resource_id)
        ))

    def import_value(self, resource_id):
        """ Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/intrinsic-function-reference-importvalue.html
        """
        return ImportValue(Sub(
            '{}-{}'.format(self.reference_param, resource_id)
        ))
