#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "TODO: Make sure your current/valid AWS environment is for: smaht-wolf"
IDENTITY=C4AppConfigFoursightSmahtDevelopment
$DIR/../setup.sh smaht-wolf $IDENTITY
resolve-foursight-checks --env_name smaht-wolf --app smaht
echo "TO DEPLOY FOURSIGHT RUN: poetry run cli provision foursight-smaht --upload-change-set --stage prod --foursight-identity $IDENTITY"
