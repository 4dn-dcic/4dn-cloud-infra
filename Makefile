default: info

.PHONY: alpha legacy deploy-alpha-p1 deploy-alpha-p2

alpha:
	@echo 'Validating CGAP-Portal Alpha'
	./4dn-cloud-infra provision network --validate --alpha
	./4dn-cloud-infra provision datastore --validate --alpha
	./4dn-cloud-infra provision iam --validate --alpha
	./4dn-cloud-infra provision ecr --validate --alpha
	./4dn-cloud-infra provision logging --validate --alpha
	./4dn-cloud-infra provision ecs --validate --alpha
	# TODO provision foursight
	# TODO provision Tibanna
	@echo 'Validation Succeeded! Note that this does NOT mean the stacks will build - consider a "light check".'

legacy:
	@echo 'Validating CGAP-Portal Legacy'
	./4dn-cloud-infra provision c4-network-trial --validate
	./4dn-cloud-infra provision c4-datastore-trial --validate
	./4dn-cloud-infra provision c4-beanstalk-trial --validate
	# TODO provision foursight
	# TODO provision Tibanna
	@echo 'Validation Succeeded!'

deploy-alpha-p1:
	@echo 'Uploading Templates for Alpha Configuration'
	@echo 'ORDER: iam, logging, network, ecr, datastore, ecs'
	./4dn-cloud-infra provision iam --validate --alpha --upload_change_set
	./4dn-cloud-infra provision logging --validate --alpha --upload_change_set
	./4dn-cloud-infra provision network --validate --alpha --upload_change_set
	./4dn-cloud-infra provision ecr --validate --alpha --upload_change_set
	# ./4dn-cloud-infra provision datastore --validate --alpha --upload_change_set
	# TODO deploy foursight

deploy-alpha-p2:
	python scripts/upload_application_version.py
	# ./4dn-cloud-infra provision ecs --validate --alpha --upload_change_set

info:
	@: $(info Here are some 'make' options:)
	   $(info - Use 'make alpha' to trigger validation of the alpha stack.)
   	   $(info - Use 'make legacy' to trigger validation of the legacy stack.)
   	   $(info - Use 'make deploy-alpha-p1' to trigger phase 1 of the alpha deployment: change set upload of the IAM, Logging, Network, ECR and Datastore.)
   	   $(info - Use 'make deploy-alpha-p2' to trigger phase 2 of the alpha deployment: application version upload to ECR, ECS provisioning.)
