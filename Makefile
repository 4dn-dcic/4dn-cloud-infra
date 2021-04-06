.PHONY: alpha legacy

alpha:
	@echo 'Validating CGAP-Portal Alpha'
	./4dn-cloud-infra provision network --validate --alpha
	./4dn-cloud-infra provision datastore --validate --alpha
	./4dn-cloud-infra provision iam --validate --alpha
	./4dn-cloud-infra provision ecr --validate --alpha
	./4dn-cloud-infra provision logging --validate --alpha
	./4dn-cloud-infra provision ecs --validate --alpha
	@echo 'Validation Succeeded! Note that this does NOT mean the stacks will build - consider a "light check".'

legacy:
	@echo 'Validating CGAP-Portal Legacy'
	./4dn-cloud-infra provision c4-network-trial --validate
	./4dn-cloud-infra provision c4-datastore-trial --validate
	./4dn-cloud-infra provision c4-beanstalk-trial --validate
	@echo 'Validation Succeeded!'

deploy-alpha-p1:
	@echo 'Uploading Templates for Alpha Configuration'
	@echo 'ORDER: iam, logging, network, ecr, datastore, ecs'
	./4dn-cloud-infra provision iam --validate --alpha --upload_change_set
	./4dn-cloud-infra provision logging --validate --alpha --upload_change_set
	./4dn-cloud-infra provision network --validate --alpha --upload_change_set
	./4dn-cloud-infra provision ecr --validate --alpha --upload_change_set
	./4dn-cloud-infra provision datastore --validate --alpha --upload_change_set
	# ./4dn-cloud-infra provision ecs --validate --alpha --upload_change_set

deploy-alpha-p2:
	python scripts/upload_application_version.py
