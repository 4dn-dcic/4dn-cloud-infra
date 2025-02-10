#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -ne 2 ]]; then
    echo "usage: $0 custom_directories_sub_directory_name identity_environment_variable_name"
    exit 1
fi

ENV=$1
IDENTITY=$2
THIS_SETUP_DIR=$DIR/$ENV

if [[ -d "$THIS_SETUP_DIR" ]]; then
    echo "Setting up custom directory for: $ENV"
else
    echo "ERROR: sub-directory not found - $THIS_SETUP_DIR"
    exit 1
fi

THIS_CUSTOM_DIR=$THIS_SETUP_DIR/custom
YOUR_BASE_DIR=$THIS_SETUP_DIR/../..
YOUR_CUSTOM_DIR=$YOUR_BASE_DIR/custom

AUTH0_CLIENT=`aws-get-secret $IDENTITY/ENCODED_AUTH0_CLIENT`
AUTH0_SECRET=`aws-get-secret $IDENTITY/ENCODED_AUTH0_SECRET`
S3_ENCRYPT_KEY=`aws-get-secret $IDENTITY/S3_ENCRYPT_KEY`

if [[ -z "$AUTH0_CLIENT" ]]; then
    echo "ERROR: cannot set AUTH0_CLIENT"
    exit 1
fi
if [[ -z "$AUTH0_SECRET" ]]; then
    echo "ERROR: cannot set AUTH0_SECRET"
    exit 1
fi
if [[ -z "$S3_ENCRYPT_KEY" ]]; then
    echo "ERROR: cannot set S3_ENCRYPT_KEY"
    exit 1
fi

rm -rf $THIS_CUSTOM_DIR ; mkdir -p $THIS_CUSTOM_DIR

cp $THIS_SETUP_DIR/template.config.json $THIS_CUSTOM_DIR/config.json

sed -e "s/\${AUTH0_CLIENT}/$AUTH0_CLIENT/ ; s/\${AUTH0_SECRET}/$AUTH0_SECRET/" $THIS_SETUP_DIR/template.secrets.json > $THIS_CUSTOM_DIR/secrets.json
chmod 400 $THIS_CUSTOM_DIR/secrets.json

echo $S3_ENCRYPT_KEY > $THIS_CUSTOM_DIR/s3_encrypt_key.txt
chmod 400 $THIS_CUSTOM_DIR/s3_encrypt_key.txt

ln -s ~/.aws $THIS_CUSTOM_DIR/aws_creds

rm -f $YOUR_CUSTOM_DIR
ln -s $THIS_SETUP_DIR/custom $YOUR_CUSTOM_DIR

if [[ -f $THIS_SETUP_DIR/chalice.config.json ]]; then
    rm -f $YOUR_BASE_DIR/.chalice/config.json
    ln -f -s $THIS_SETUP_DIR/chalice.config.json  $YOUR_BASE_DIR/.chalice/config.json
fi
