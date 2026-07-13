# redis module — faithful port of src/parts/redis.py (C4Redis, SHARING='env' default).
#
# Scope: ENV-scoped -> each envs/<env>/ root. Encryption at-rest and in-transit are enabled
# (redis.py:71-72), automatic failover disabled (redis.py:69).

locals {
  env_camel = join("", [for w in split("-", var.env_name) : title(w)])
}

resource "aws_elasticache_subnet_group" "this" {
  name        = "${var.env_name}-redis-subnet-group"
  description = "Subnet group for Redis cache cluster associated with ${var.env_name}"
  subnet_ids  = var.private_subnet_ids
  tags        = var.tags
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id       = "${local.env_camel}Redis"
  description                = "Pass additional options to the Redis Cluster"
  engine                     = "redis"
  engine_version             = var.engine_version
  node_type                  = var.node_type
  num_cache_clusters         = var.node_count
  automatic_failover_enabled = false
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auto_minor_version_upgrade = true
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [var.application_security_group_id]
  tags                       = var.tags
}
