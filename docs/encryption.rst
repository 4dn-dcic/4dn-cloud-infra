Encryption Documentation
------------------------

Most services work with encryption out of the box. This main focus of this documentation
is working with KMS, IAM and S3 to enable KMS based encryption by default on S3 buckets
other than the system bucket (which is still encrypted via the customer managed key).

KMS Prerequisite
----------------

KMS relies on symmetric IAM policies - that is, both the calling IAM entity and the KMS
key itself must have correct permissions. The IAM entity can reference KMS broadly, but
the key policy itself should be specific to the roles within the account. Upon deploying,
this policy contains entries for the ApplicationS3Federator (and deploying IAM user
or SSO role). You must add all other executor roles to the KMS policy, namely the
Foursight check runner and API handlers along with the executor role for Tibanna.


S3
--

Encryption of S3 files occurs through two different keys. Files in the system bucket are
encrypted using the customer managed ``S3_ENCRYPT_KEY``. All other buckets are encrypted
with an Amazon Managed KMS Key, referenced by ``S3_ENCRYPT_KEY_ID``. Note that these keys
are in fact different. When ``S3_ENCRYPT_KEY_ID`` is set, the application presumes S3
encryption is enabled. The buckets have a policy on them that will force them to reject
uploads that do not specify the correct KMS encryption key (the ID).

