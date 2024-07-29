from ..base import ConfigManager
from ..constants import Settings, Secrets


class CrowdStrikeContainerSensor:

    # This is meant to be manually populated, so we do not leak
    # the API keys through the template itself
    CONFIGURATION_PLACEHOLDER = 'XXX: ENTER VALUE'

    @classmethod
    def build_initial_values(cls):
        """ Returns a dictionary of key/values """
        return {

            # These are specific to our services
            'FALCON_CLIENT_ID': cls.CONFIGURATION_PLACEHOLDER,
            'FALCON_CLIENT_SECRET': cls.CONFIGURATION_PLACEHOLDER,

            # This CID identifies us as HMS
            'FALCON_CID': cls.CONFIGURATION_PLACEHOLDER,

            # These are specific to CS itself
            'FALCON_CLOUD_API': cls.CONFIGURATION_PLACEHOLDER,
            'FALCON_REGION': cls.CONFIGURATION_PLACEHOLDER,
            'FALCON_CONTAINER_REGISTRY': cls.CONFIGURATION_PLACEHOLDER,

            # These require generation using the above credentials
            'FALCON_CS_API_TOKEN': cls.CONFIGURATION_PLACEHOLDER,
            'FALCON_ART_USERNAME': cls.CONFIGURATION_PLACEHOLDER,
            'FALCON_ART_PASSWORD': cls.CONFIGURATION_PLACEHOLDER,
            'REGISTRY_BEARER': cls.CONFIGURATION_PLACEHOLDER,

            'SENSORTYPE': 'falcon-container',
            'FALCON_SENSOR_IMAGE_REPO': cls.CONFIGURATION_PLACEHOLDER,
            'FALCON_SENSOR_IMAGE_TAG': cls.CONFIGURATION_PLACEHOLDER,

        }
