# SRCE network shells

Consolidates the Application, Database and retained Compute shells' seven owned SGs/rules.
VPCs/subnets/CIDRs are required inputs, not created resources or AWS-discovered data sources.
IT retains routes/NAT/endpoints/logging/CloudTrail. IDs cannot prove actual membership or AZs.

Outputs include separate typed `application_network`, `database_network`, `compute_network`.
ECS/CodeBuild/Foursight/Sentieon use Application; datastore/Redis use Database. See
`terraform/PARITY.md` for the complete rule comparison and implicit-default-egress preservation.
