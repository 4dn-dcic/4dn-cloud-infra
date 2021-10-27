=================
Account Migration
=================
How data is moved from account to account.
----------------------------------------------------------------------------

The AWS documentation page
`Copy data from an S3 bucket in one account and Region to another account and Region
<https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/copy-data-from-an-s3-bucket-in-one-account-and-region-to-another-account-and-region.html>`_
is a useful source of data.

Create a permission document on each of the buckets to be transferred that looks like::

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DelegateS3Access",
                "Effect": "Allow",
                "Principal": {"AWS": "arn:aws:iam::123123123123:user/your.iam.here"},
                "Action": ["s3:ListBucket","s3:GetObject"],
                "Resource": [
                    "arn:aws:s3:::elasticbeanstalk-ENVNAME-SUFFIX/*",
                    "arn:aws:s3:::elasticbeanstalk-ENVNAME-SUFFIX"
                ]
            }
        ]
    }

where

* ``123`` should be replaced by your AWS account number, and where
* ``ENVNAME`` is replaced by the name of an environment such as ``fourfront-cgapwolf``, and where
* ``SUFFIX`` is replaced by the bucket name suffix for the bucket you are wanting to copy (``blobs``, etc.)

