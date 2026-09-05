==========================================
CrowdStrike Falcon sensor on ECS (Fargate)
==========================================

Overview
--------

The ECS stacks can optionally attach the **CrowdStrike Falcon container sensor** to every ECS task
(portal, indexer, ingester, and deployment tasks) as a *sidecar*, following the vendor's
container-sensor pattern for Fargate. The feature is **off by default**: unless
``crowdstrike.enabled`` is set to ``true`` in ``config.json``, the emitted task definitions are
byte-identical to their pre-CrowdStrike form (a single application container, no shared volume).

When enabled, each task definition gains:

* a **non-essential** ``falcon-container`` sidecar (the ``falcon-sensor`` image built into ECR by
  the CodeBuild stack) that **prepares a shared ``crowdstrike-falcon-volume``** — a task-level
  ``Host`` volume — and receives the Falcon **CID** from Secrets Manager as the
  ``FALCONCTL_OPT_FALCONCTL_CID`` environment variable, plus ``FALCONCTL_OPT_BACKEND`` (default
  ``bpf``);
* the application container mounts that shared volume **read-only**, is wrapped by the CrowdStrike
  **loader entrypoint**, and declares a ``dependsOn`` on the sidecar with condition ``SUCCESS`` so
  it does not start until the sidecar has populated the volume and exited successfully.

This applies uniformly to the CGAP, Fourfront, SMaHT, blue/green, and SRCE ECS variants — the wiring
lives on the shared base class (``C4ECSApplication._crowdstrike_task_kwargs``) so no variant is left
inconsistent.

Nothing in the generated templates hard-codes an AWS account id, secret ARN, image tag, log group,
or environment identifier. Every input is resolved through existing cross-stack parameters/exports:

============================  ========================================================================
Input                         Source
============================  ========================================================================
Falcon sensor image           ECR export ``FalconSensorURL`` (the ``falcon-sensor`` repo)
Falcon CID secret ARN         AppConfig export ``ExportFalconCID`` (env-scoped, one per env)
IAM task/execution role       IAM export ``ECSAssumedIAMRole`` (unchanged)
Log group                     Logging export(s) (the same per-color group in blue/green)
Region                        ``AWS::Region``
============================  ========================================================================

Configuration keys
-------------------

Set these under the ``config.json`` used for the ECS stack:

* ``crowdstrike.enabled`` — ``true`` to attach the sidecar; default ``false``.
* ``crowdstrike.entrypoint`` — **required when enabled, no default.** The CrowdStrike loader
  entrypoint the application container is wrapped with, as a JSON list (``["/path/loader", ...]``)
  or a comma-separated string. This is a **vendor/image-specific contract**: the exact value must
  come from the ``falcon-sensor`` image configuration / CrowdStrike's ECS Fargate documentation and
  must be reconciled with the application image's own entrypoint. There is deliberately no default,
  because a wrong or empty entrypoint would produce a task definition that *validates but never runs
  the application*. Enabling CrowdStrike without this key raises a build-time error.
* ``crowdstrike.mount_path`` — where the shared volume is mounted in both containers; default
  ``/tmp/CrowdStrike``.
* ``crowdstrike.sensor_image_tag`` — tag for the ``falcon-sensor`` image; default ``latest``.
* ``crowdstrike.backend`` — value for ``FALCONCTL_OPT_BACKEND``; default ``bpf``.

Prerequisites and external inputs
---------------------------------

Enabling CrowdStrike depends on things owned outside this repo; confirm each before flipping the
flag:

#. **Falcon CID populated.** The AppConfig stack creates a *stub* ``FalconCID`` secret; its value
   must be filled in post-deploy (see ``setup-remaining-secrets`` and
   :doc:`deploy_new_account`). Add its exact physical secret name to
   ``iam.ecosystem_resources.runtime_secrets`` (:doc:`iam_inventory`). The ECS execution role
   does not get broad ``C4AppConfig*`` access or Falcon API ClientID/ClientSecret access.
#. **falcon-sensor image present in ECR.** The CodeBuild pipeline builds and pushes it; the tag must
   match ``crowdstrike.sensor_image_tag``.
#. **Loader entrypoint verified.** ``crowdstrike.entrypoint`` must match the falcon-sensor image's
   documented loader contract. This cannot be validated offline from this repo — verify it against
   the image config / vendor PDF.
#. **Sidecar lifecycle.** The ``dependsOn`` uses condition ``SUCCESS``, which assumes the sensor
   image is *prepare-and-exit* (populates the volume, then exits 0). If a future sensor image runs
   persistently instead, this must change to ``COMPLETE`` or wrapped tasks will deadlock in
   ``PENDING``.
#. **Task memory headroom.** Adding the sidecar increases per-task memory pressure. The small tasks
   in particular — the indexer (defaults ``256``/``512``) and ingester — will likely need
   ``ecs.indexer.cpu``/``ecs.indexer.memory`` (and the ingester pair) raised before enabling
   CrowdStrike. The defaults are intentionally left unchanged so non-CrowdStrike deployments are
   unaffected.

Verification and rollback
-------------------------

Because task definitions are one revision each, enabling/disabling is a redeploy, not a mutation:

* **Verify:** provision the ECS stack, then in the ECS console confirm each task definition has two
  containers (``<app>`` + ``falcon-container``), the shared ``crowdstrike-falcon-volume``, the app's
  read-only mount and ``dependsOn``, and the sidecar's ``FALCONCTL_OPT_FALCONCTL_CID`` secret. Run a
  task and confirm the sidecar exits 0 and the application starts and reaches ``/health``.
* **Rollback:** set ``crowdstrike.enabled`` back to ``false`` and re-provision; the next revision is
  the original single-container definition. Services pick up the new revision on their next
  deployment.
