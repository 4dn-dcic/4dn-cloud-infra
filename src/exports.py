import re
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


# dmichaels/2022-07-14: Refactored out of base.py.
USE_SHORT_EXPORT_NAMES = True  # TODO: Remove when debugged


# dmichaels/2022-07-14: Refactored out of base.py.
def exportify(name):
    return name if USE_SHORT_EXPORT_NAMES else f"Export{name}"


# dmichaels/2022-07-14: Refactored of database.py/C4DatastoreExports.
class C4DatastoreExportsMixin:
    # Output ES URL for use by foursight/application
    ES_URL = exportify('ElasticSearchURL')
    BLUE_ES_URL = exportify('BlueESURL')
    GREEN_ES_URL = exportify('GreenESURL')

    # RDS Exports
    RDS_URL = exportify('RdsUrl')
    RDS_PORT = exportify('RdsPort')

    # Output secrets info
    APPLICATION_CONFIGURATION_SECRET_NAME = exportify("ApplicationConfigurationSecretName")

    # Output env bucket and result bucket
    FOURSIGHT_ENV_BUCKET = exportify('FoursightEnvBucket')
    FOURSIGHT_RESULT_BUCKET = exportify('FoursightResultBucket')
    FOURSIGHT_APPLICATION_VERSION_BUCKET = exportify('FoursightApplicationVersionBucket')

    # Output production S3 bucket information
    # NOTE: Some of these have output names for historical reasons that do not well match what the bucket names are.
    #       The names are just formal names, so we'll live with that for now. -kmp 29-Aug-2021
    APPLICATION_SYSTEM_BUCKET = exportify('AppSystemBucket')
    APPLICATION_WFOUT_BUCKET = exportify('AppWfoutBucket')
    APPLICATION_FILES_BUCKET = exportify('AppFilesBucket')
    APPLICATION_BLOBS_BUCKET = exportify('AppBlobsBucket')
    APPLICATION_METADATA_BUNDLES_BUCKET = exportify('AppMetadataBundlesBucket')
    APPLICATION_TIBANNA_OUTPUT_BUCKET = exportify('AppTibannaLogsBucket')
    APPLICATION_TIBANNA_CWL_BUCKET = exportify('AppTibannaCWLBucket')

    # Output SQS Queues
    APPLICATION_INDEXER_PRIMARY_QUEUE = exportify('ApplicationIndexerPrimaryQueue')
    APPLICATION_INDEXER_SECONDAY_QUEUE = exportify('ApplicationIndexerSecondaryQueue')
    APPLICATION_INDEXER_DLQ = exportify('ApplicationIndexerDLQ')
    APPLICATION_INGESTION_QUEUE = exportify('ApplicationIngestionQueue')
    APPLICATION_INDEXER_REALTIME_QUEUE = exportify('ApplicationIndexerRealtimeQueue')  # unused

    # e.g., name will be C4DatastoreTrialAlphaExportElasticSearchURL
    #       or might not contain '...Alpha...'
    _ES_URL_EXPORT_PATTERN = re.compile(f'.*Datastore.*{ES_URL}.*')
    # _ES_URL_EXPORT_PATTERN = re.compile('.*Datastore.*ElasticSearchURL.*')
