variable "bastion" {
  description = "Opt-in network.bastion.*; skipped unless enabled AND AMI/key provided, matching CFN."
  type        = object({ enabled = optional(bool, false), ami = optional(string, ""), ssh_key = optional(string, "") })
  default     = {}
}
resource "aws_instance" "bastion" {
  count                       = var.bastion.enabled && var.bastion.ami != "" && var.bastion.ssh_key != "" ? 1 : 0
  ami                         = var.bastion.ami
  instance_type               = "t2.nano"
  key_name                    = var.bastion.ssh_key
  subnet_id                   = aws_subnet.public[local.first_public_key].id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.application.id]
  tags                        = merge(var.tags, { Name = "${var.name_prefix}-bastion-host" })
}
