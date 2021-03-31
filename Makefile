alpha:
	echo 'Validating CGAP-Portal Alpha'
	 ./4dn-cloud-infra provision network --validate --alpha
	./4dn-cloud-infra provision datastore --validate --alpha
	./4dn-cloud-infra provision iam --validate --alpha
	./4dn-cloud-infra provision ecr --validate --alpha
	./4dn-cloud-infra provision logging --validate --alpha
	./4dn-cloud-infra provision ecs --validate --alpha 
	echo 'Validation Succeeded! Note that this does NOT mean the stacks will build - consider a "light check".'
