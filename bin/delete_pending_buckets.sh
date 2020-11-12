#!/usr/bin/env bash

set -v -x

for i in `cat pending_deletion`
do
echo "force deleting ${i}...press key to proceed or ctrl+c to cancel"
read line
echo "would delete here, ls first"
echo "follow progress with:"
echo "tail -f ../out/delete_log_${i}.log"
#docker run --rm -ti -v ~/.aws:/root/.aws amazon/aws-cli s3 rb s3://${i} --force >> ../out/delete_log_${i}.log
docker run --rm -ti -v ~/.aws:/root/.aws amazon/aws-cli s3 ls s3://${i} --summarize >> ../out/delete_log_${i}.log
done

