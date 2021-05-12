default: info

.PHONY: alpha legacy deploy-alpha-p1 deploy-alpha-p2 info

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
	@echo 'CGAP Orchestration Phase 1: Uploading Base Templates'
	@echo 'ORDER: iam, logging, network, ecr, datastore'
	./4dn-cloud-infra provision iam --validate --alpha --upload_change_set
	./4dn-cloud-infra provision logging --validate --alpha --upload_change_set
	./4dn-cloud-infra provision network --validate --alpha --upload_change_set
	./4dn-cloud-infra provision ecr --validate --alpha --upload_change_set
	./4dn-cloud-infra provision datastore --validate --alpha --upload_change_set
	@echo 'Datastore stacks takes ~15 minutes to come online.'
	@echo 'While this happens, you should be:'
	@echo '    1. Uploading your application images to ECR.'
	@echo '       To upload application versions to ECR, see cgap-portal: src/deploy/docker/production/Makefile'
	@echo '       Required Image Tags: "latest", "latest-indexer", "latest-ingester", "latest-deployment"'
	@echo '    2. Writing your environment configuration in secretsmanager.'
	# TODO deploy foursight ? might belong in next step

deploy-alpha-p2:
	@echo -n "Confirm you have done the 2 required steps after deploy-alpha-p1 with 'y' [y/N] " && read ans && [ $${ans:-N} = y ]
	./4dn-cloud-infra provision ecs --validate --alpha --upload_change_set
	@echo 'ECS may take up to 10 minutes to come online. Once it has, examine the stack output for the URL.'
	@echo 'Next, upload base environment configuration to global application s3 bucket.'
	@echo 'Phase 3 is triggering deployment, which for now is done manually from the ECS console.'
	@echo 'Feel free to skip this step if you do not wish to run the deployment.'
	@echo 'Instructions:'
	@echo '    * Navigate to the ECS Console and locate the Deployment Service.'
	@echo '    * Invoke this task in the newly created VPC and private subnets.'
	@echo '    * Attach the Application and DB Security groups.'
	@echo 'Once the deployment container is online, logs will immediately stream to the task/Cloudwatch.'

provision-knowledge-base:
	@echo 'Loading knowledge base information'

test:
	@echo 'Running end-to-end test'
	@echo 'Phase 1: Metadata Bundle Submission for Demo Case NA 12879'
	@echo 'NOTE: This test is intended to be run on the Trial Account ECS only (for now)'
	poetry run submit-metadata-bundle test_data/na_12879/na12879_accessioning.xlsx --s http://c4ecstrialalphaecslb-2115269186.us-east-1.elb.amazonaws.com
	@echo 'NOTE: Bypassing Bioinformatics by uploading raw VCF directly.'
	python scripts/upload_file_processed.py
	docker run --rm -v ~./aws_test:/root/.aws amazon/aws-cli s3 cp test_data/na_12879/GAPFI9V6TEQA.vcf.gz s3://application-cgap-mastertest-wfout/3535ce97-b8e6-4ed2-b4fc-dcab7aebcc0f/GAPFI9V6TEQA.vcf.gz
	python scripts/queue_ingestion.py
	@echo 'Ingestion queued - see CloudWatch Ingester logs'

info:
	@: $(info Here are some 'make' options:)
	   $(info - Use 'make alpha' to trigger validation of the alpha stack.)
   	   $(info - Use 'make legacy' to trigger validation of the legacy stack.)
   	   $(info - Use 'make deploy-alpha-p1' to trigger phase 1 of the alpha deployment: change set upload of the IAM, Logging, Network, ECR and Datastore.)
   	   $(info - Use 'make deploy-alpha-p2' to trigger phase 2 of the alpha deployment: application version upload to ECR, ECS provisioning.)
