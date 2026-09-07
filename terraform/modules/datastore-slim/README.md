# Legacy slim datastore

Implemented by `../datastore` with `variant = "slim"`, not a duplicate resource module.
Consumes legacy VPC subnet/SG IDs and owns RDS plus `es-` Elasticsearch 6.8 domains; no S3, SQS
or KMS key. Explicit PostgreSQL versions drive both engine and parameter family; default 17.6.
See `terraform/PARITY.md` for conservative native RDS protection/backup differences and adoption.
