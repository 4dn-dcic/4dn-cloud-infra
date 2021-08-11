default: info

.PHONY: alpha legacy deploy-alpha-p1 deploy-alpha-p2 info

build:
	poetry install

alpha:
	@echo 'Validating CGAP-Portal Alpha'
	poetry run cli provision network --validate --alpha
	poetry run cli provision datastore --validate --alpha
	poetry run cli provision iam --validate --alpha
	poetry run cli provision ecr --validate --alpha
	poetry run cli provision logging --validate --alpha
	poetry run cli provision ecs --validate --alpha
	# TODO validate foursight
	# TODO provision Tibanna
	@echo 'Validation Succeeded! Note that this does NOT mean the stacks will build - consider a "light check".'

legacy:
	@echo 'Validating CGAP-Portal Legacy'
	poetry run cli provision c4-network-trial --validate
	poetry run cli provision c4-datastore-trial --validate
	poetry run cli provision c4-beanstalk-trial --validate
	# TODO provision foursight
	# TODO provision Tibanna
	@echo 'Validation Succeeded!'

deploy-alpha-p1:
	@echo 'CGAP Orchestration Phase 1: Uploading Base Templates'
	@echo 'ORDER: iam, logging, network, ecr, datastore'
	poetry run cli provision iam --validate --alpha --upload_change_set
	poetry run cli provision logging --validate --alpha --upload_change_set
	poetry run cli provision network --validate --alpha --upload_change_set
	poetry run cli provision ecr --validate --alpha --upload_change_set
	poetry run cli provision datastore --validate --alpha --upload_change_set
	@echo 'Datastore stacks takes ~15 minutes to come online.'
	@echo 'While this happens, you should be:'
	@echo '    1. Uploading your application images to ECR.'
	@echo '       To upload application versions to ECR, see cgap-portal: src/deploy/docker/production/Makefile'
	@echo '       Required Image Tags: "latest", "latest-indexer", "latest-ingester", "latest-deployment"'
	@echo '    2. Writing your environment configuration in secretsmanager.'
	# TODO deploy foursight ? might belong in next step

deploy-alpha-p2:
	@echo -n "Confirm you have done the 2 required steps after deploy-alpha-p1 with 'y' [y/N] " && read ans && [ $${ans:-N} = y ]
	poetry run cli provision ecs --validate --alpha --upload_change_set
	poetry run cli provision --trial --output_file out/foursight-dev-tmp/ --stage dev foursight --alpha --upload_change_set
	@echo 'ECS may take up to 10 minutes to come online. Once it has, examine the stack output for the URL.'
	@echo 'Next, upload base environment configuration to global application s3 bucket.'
	@echo 'Phase 3 is triggering deployment, which for now is done manually from the ECS console.'
	@echo 'Feel free to skip this step if you do not wish to run the deployment.'
	@echo 'Instructions:'
	@echo '    * Navigate to the ECS Console and locate the Deployment Service.'
	@echo '    * Invoke this task in the newly created VPC and private subnets.'
	@echo '    * Attach the Application and DB Security groups.'
	@echo 'Once the deployment container is online, logs will immediately stream to the task/Cloudwatch.'
	@echo 'After the deployment is complete, if this is the first deploy, load the knowledge base'
	@echo 'With: "make provision-knowledge-base".'

provision-knowledge-base:
	@echo 'Loading knowledge base information (variant_consequences and genes)'
	poetry run load-knowledge-base
	@echo 'Knowledge base loaded, ready for end-to-end test.'
	@echo 'Start with: "make submission".'

submission:
	@echo 'Running end-to-end test'
	@echo 'Phase 1: Metadata Bundle Submission for Demo Case NA 12879'
	@echo 'NOTE: This test is intended to be run on the Trial Account ECS only (for now)'
	poetry run submit-metadata-bundle test_data/na_12879/na12879_accessioning.xlsx --s http://c4ecstrialalphacgapmastertest-273357903.us-east-1.elb.amazonaws.com
	@echo 'NOTE: Bypassing Bioinformatics by uploading raw VCF directly.'
	poetry run upload-file-processed
	docker run --rm -v ~/aws_test:/root/.aws amazon/aws-cli s3 cp test_data/na_12879/GAPFI9V6TEQA.vcf.gz s3://application-cgap-mastertest-wfout/3535ce97-b8e6-4ed2-b4fc-dcab7aebcc0f/GAPFI9V6TEQA.vcf.gz
	@echo 'Now, navigate to the portal and verify the uploaded processed file exists.'
	@echo 'Then, locate the sample processing item for the submitted case.'
	@echo 'Associate this item with the output VCF by adding the VCF file to the "processed_files" field.'
	@echo 'Once this is done, trigger ingestion with: "make ingestion". '


ingestion:
	@echo 'Triggering ingestion'
	poetry run queue-ingestion
	@echo 'Ingestion queued - check CloudWatch Ingester logs'

info:
	@: $(info Here are some 'make' options:)
	   $(info - Use 'make alpha' to trigger validation of the alpha stack.)
	   $(info - Use 'make build' to populate the current virtualenv with necessary libraries and commands.)
	   $(info - Use 'make legacy' to trigger validation of the legacy stack.)
	   $(info - Use 'make deploy-alpha-p1' to trigger phase 1 of the alpha deployment: change set upload of the IAM, Logging, Network, ECR and Datastore.)
	   $(info - Use 'make deploy-alpha-p2' to trigger phase 2 of the alpha deployment: application version upload to ECR, ECS provisioning.)
	   $(info - use 'make provision-knowledge-base' to trigger phase 1 of testing)
	   $(info - use 'make submission' to trigger phase 2 of testing, note manual steps after phase 2!)
	   $(info - use 'make ingestion' to trigger the last phase of testing)
