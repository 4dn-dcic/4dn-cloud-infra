output "private_ip" { value = aws_instance.this.private_ip }
output "instance_id" { value = aws_instance.this.id }
output "application_url" { value = try("http://${aws_lb.this[0].dns_name}", null) }
