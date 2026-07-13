# `datastore-slim` — DEFERRED in this PR

Fourfront legacy datastore variant from `src/parts/datastore_slim.py`. Kept a SEPARATE module from
`datastore` (plan §2.4) — different wiring and a different search engine. Not yet implemented; the
4dn env roots reference it only as commented `# module "datastore_slim"` TODOs.

## When implemented, faithful to datastore_slim.py

- Same RDS shape as `modules/datastore`, BUT the search engine is **legacy `troposphere.elasticsearch.Domain`
  (Elasticsearch 6.8)** — `aws_elasticsearch_domain`, NOT `aws_opensearch_domain`
  (datastore_slim.py:191-236).
- VPC/subnets/SGs are **parameter-injected**, not `ImportValue` (datastore_slim.py:66-138) — the
  4dn account's legacy-VPC wiring. In Terraform: consume `modules/network-data` outputs (the
  `data`-source wrapper over `vpc-066421dc99161d0ea`), NOT a remote-state read of a managed network.
- Deferred because it is only in the 4dn account, which has **no fresh-account create-path
  validation** (plan §10.3); it gets its own import session (plan §3 Phase 4).
