# CFN creates these groups without inline egress, then adds separate rules. EC2's initial
# all-egress rule remains; Terraform removes it on creation unless explicitly retained here.
# This is compatibility, NOT a claim of restrictive outbound isolation.
resource "aws_security_group_rule" "default_egress" {
  for_each          = { db = aws_security_group.db.id, https = aws_security_group.https.id, application = aws_security_group.application.id }
  security_group_id = each.value
  type              = "egress"
  protocol          = "-1"
  from_port         = 0
  to_port           = 0
  cidr_blocks       = ["0.0.0.0/0"]
}
variable "flow_log_role_name" {
  description = "Discovered FlowLog delivery role name for adoption, preserving the CFN-generated identity."
  type        = string
  default     = null
}
