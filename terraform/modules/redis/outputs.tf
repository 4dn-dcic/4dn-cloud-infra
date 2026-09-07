# redis.py exports nothing today (C4RedisExports is empty; output_redis_endpoint is never called —
# redis.py:12-14,39-47). These outputs are additive and safe: no CFN export name to stay compatible
# with, so nothing downstream regex-matches them.

output "primary_endpoint_address" {
  description = "Redis primary endpoint address."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "replication_group_id" {
  value       = aws_elasticache_replication_group.this.replication_group_id
  description = "Replication group id."
}
