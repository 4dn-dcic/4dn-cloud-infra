#!/bin/bash

THIS_SETUP_DIR=`realpath $(dirname $BASH_SOURCE)`
THIS_CUSTOM_DIR=$THIS_SETUP_DIR/custom
YOUR_CUSTOM_DIR=$THIS_SETUP_DIR/../../custom

IDENTITY=FoursightProductionApplicationConfiguration
AUTH0_CLIENT=`aws-get-secret ${IDENTITY}/ENCODED_AUTH0_CLIENT`
AUTH0_SECRET=`aws-get-secret ${IDENTITY}/ENCODED_AUTH0_SECRET`
S3_ENCRYPT_KEY=`aws-get-secret ${IDENTITY}/S3_ENCRYPT_KEY`

rm -rf $THIS_CUSTOM_DIR
mkdir -p $THIS_CUSTOM_DIR

cp $THIS_SETUP_DIR/template.config.json $THIS_CUSTOM_DIR/config.json

sed -e "s/\${AUTH0_CLIENT}/$AUTH0_CLIENT/ ; s/\${AUTH0_SECRET}/$AUTH0_SECRET/" $THIS_SETUP_DIR/template.secrets.json > $THIS_CUSTOM_DIR/secrets.json
chmod 400 $THIS_CUSTOM_DIR/secrets.json

echo $S3_ENCRYPT_KEY > $THIS_CUSTOM_DIR/s3_encrypt_key.txt
chmod 400 $THIS_CUSTOM_DIR/s3_encrypt_key.txt

ln -s ~/.aws $THIS_CUSTOM_DIR/aws_creds

rm -f $YOUR_CUSTOM_DIR
ln -s $THIS_SETUP_DIR/custom $YOUR_CUSTOM_DIR
