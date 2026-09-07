# ec2-service

Environment-scoped native Higlass, JupyterHub and standard/SRCE Sentieon contracts.
Sentieon consumes Application networking; Compute gets only cross-VPC license access.
User-data files are preserved from the source generators and compared offline, never executed
by validation. Their old dependencies/images still require operator review before use.

Auxiliary web ALBs remain HTTP with manual target registration, matching current CFN.
No claim of auxiliary TLS, verified AMI usability or hardened legacy web-service SSH is made.
See `terraform/PARITY.md` and `variables.tf` for inputs and adoption differences.
