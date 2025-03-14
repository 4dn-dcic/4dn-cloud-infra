#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "TODO: Make sure your current/valid AWS environment is for: smaht-prod"
IDENTITY=C4AppConfigFoursightSmahtProduction
$DIR/../setup.sh smaht-prod $IDENTITY
resolve-foursight-checks --env_name data --app smaht
echo "TO DEPLOY FOURSIGHT RUN: poetry run cli provision foursight-smaht --upload-change-set --stage prod --foursight-identity $IDENTITY"
