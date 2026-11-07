# Deployment permissions for `SMaHT-Deployment-Manager` (account 517723527581, us-east-1)

These files are the infrastructure deployment permissions from `src/parts/iam.py`
(`C4IAM.human_deploy_policy_documents`). They are rendered as plain IAM JSON for AWS account
**517723527581** and Region **us-east-1**, for the **existing** IAM Identity Center permission set
**`SMaHT-Deployment-Manager`**.

- **No editing needed.** Every account and Region value is filled in. The `*` wildcards inside
  ARNs are deliberate scope selectors, such as `stack/c4-*/*`.
- **Same permissions as the opt-in role.** They are exactly the documents the opt-in
  `*InfraDeployRole` uses, statement for statement. `tests/test_deploy_policy_bundle.py` checks
  this.
- **Regenerate, don't hand-edit.** When `src/parts/iam.py` changes, run
  `python -m src.commands.render_deploy_policy_bundle --account-id 517723527581 --region us-east-1 --permission-set SMaHT-Deployment-Manager --policy-prefix SMaHT --out docs/examples/smaht-deployment-manager-517723527581-us-east-1`.
  Add `--check` to only verify.

## What goes where

| File | Attach as | Name and path | Size (limit) |
|---|---|---|---|
| `SMaHTInfraDeployStackPolicy.json` | Customer managed policy, created in account 517723527581 | `SMaHTInfraDeployStackPolicy`, path `/` | 5,483 of 6,144 characters |
| `SMaHTInfraDeployComputePolicy.json` | Customer managed policy, created in account 517723527581 | `SMaHTInfraDeployComputePolicy`, path `/` | 5,322 of 6,144 |
| `SMaHTInfraDeployDataPolicy.json` | Customer managed policy, created in account 517723527581 | `SMaHTInfraDeployDataPolicy`, path `/` | 5,784 of 6,144 |
| `SMaHT-Deployment-Manager-inline-policy.json` | The permission set's inline policy (explicit denies only) | – | 3,738 of 10,240 non-whitespace characters, and under 32,768 bytes |
| `manifest.json` | Not attached. It records the names, paths, sizes and source above. | – | – |

These are the quotas that apply:

- **IAM:** 6,144 characters per customer managed policy, whitespace not counted.
- **IAM Identity Center:** one inline policy per permission set, at most 32,768 bytes and 10,240
  non-whitespace characters.
- **Managed policies per role:** IAM quotas apply to the role Identity Center provisions. Three
  customer managed policies and no AWS managed policies fit the default limit.

The permissions only work with all four documents attached. The three allow documents are
incomplete without the inline guardrail, which supplies the explicit denies.
Do not merge them into one policy, and do not drop any of them.

The customer managed policy names contain `InfraDeploy`. The inline policy denies every principal
holding it any change to `policy/*InfraDeploy*`, so a deployer cannot rewrite these policies.

## Who does what

- **Identity Center administrator** (management or delegated administrator account): edits the
  permission set and reprovisions it.
- **IAM administrator in account 517723527581:** creates and updates the three customer managed
  policies. Identity Center requires a customer managed policy to exist, with the same name and
  path, in every account the permission set is provisioned to before you reprovision.
- **Deployers:** need no changes. They keep signing in through Identity Center as today.

Nothing here applies itself. This guide creates no IAM role, trust policy or assignment, and you
must not edit the `AWSReservedSSO_SMaHT-Deployment-Manager_*` role directly; Identity Center owns it.

## Credentials and Region for the commands below

Every command below names `--region us-east-1` explicitly; don't rely on a profile's default
Region. Run each one with credentials for the account it targets:

- **Member-account IAM steps:** account 517723527581.
- **`sso-admin` steps:** the Identity Center management or delegated administrator account.
  us-east-1 is the Identity Center Region here: the role's ARN path has no Region segment, which
  per AWS means the identity source is hosted in us-east-1.

Get credentials the way you already do, for example by copying fresh credentials for the right
account and permission set from the AWS access portal into your shell. `aws sso login --profile
<profile>` is an option only if that local profile is already configured for IAM Identity Center.
The policy files themselves don't depend on any local CLI setup, and the console steps need none.

## Step 0 - confirm the permission set is used only in this account

In the IAM Identity Center console, open **Multi-account permissions → Permission sets →
`SMaHT-Deployment-Manager`** and read its **AWS accounts** list.

- **If it lists only 517723527581:** continue.
- **If it lists any other account, stop.** A permission set's definition is global. These policies
  name account 517723527581 and would break or mis-scope the others. Reprovisioning them would also
  fail, because the customer managed policies don't exist there. Decide the targeting first, for
  example with a separate permission set per account, before changing this one.

## Step 1 - create the customer managed policies (account 517723527581)

Run these as an IAM administrator in account 517723527581, from this directory:

```bash
aws iam create-policy --region us-east-1 --path / --policy-name SMaHTInfraDeployStackPolicy \
    --policy-document file://SMaHTInfraDeployStackPolicy.json \
    --description "Deployment role: CloudFormation change sets and generated runtime identities."
aws iam create-policy --region us-east-1 --path / --policy-name SMaHTInfraDeployComputePolicy \
    --policy-document file://SMaHTInfraDeployComputePolicy.json \
    --description "Deployment role: network, instances, load balancing, ECS, Foursight serverless."
aws iam create-policy --region us-east-1 --path / --policy-name SMaHTInfraDeployDataPolicy \
    --policy-document file://SMaHTInfraDeployDataPolicy.json \
    --description "Deployment role: datastores, keys, secrets, buckets, artifacts, registries, builds."
```

You can use the IAM console instead (**Policies → Create policy → JSON**): paste each file and use
exactly these names, with path `/`.

To update a policy later, regenerate the bundle, then run:

```bash
aws iam create-policy-version --region us-east-1 --set-as-default \
    --policy-arn arn:aws:iam::517723527581:policy/SMaHTInfraDeployStackPolicy \
    --policy-document file://SMaHTInfraDeployStackPolicy.json
```

Repeat this for each changed policy. IAM keeps at most five versions, so delete old ones as needed.
The provisioned role picks up new versions of these policies without reprovisioning.

## Step 2 - change the permission set (Identity Center administrator)

Open `SMaHT-Deployment-Manager` → **Permissions** and replace its permissions. Do not add the bundle
alongside the old permissions:

1. **AWS managed policies:** detach all of the ones it currently has: `ReadOnlyAccess`,
   `AmazonS3FullAccess`, `AmazonSSMFullAccess`, `AmazonSageMakerFullAccess` and
   `AWSSupportAccess`. If you keep any of them, the deployer also gets those broad grants. For
   example, S3 and SSM full access would add data-plane reads and writes outside these policies.
   The explicit denies would still apply. If people rely on these grants for non-deployment work,
   give them a separate permission set.
2. **Customer managed policies:** attach `SMaHTInfraDeployStackPolicy`,
   `SMaHTInfraDeployComputePolicy` and `SMaHTInfraDeployDataPolicy`, each with path `/`.
3. **Inline policy:** replace the whole existing inline policy (today's EC2 start/stop and DynamoDB
   item grants) with the contents of `SMaHT-Deployment-Manager-inline-policy.json`.
4. **Leave everything else unchanged:** session duration, relay state, tags, permissions boundary
   (none is used here) and all user and group assignments.

## Step 3 - reprovision to account 517723527581 only

After saving, the console prompts you to update the accounts where the permission set is
provisioned. Apply the update for 517723527581.

To do this from the API, look up the identifiers instead of typing them; this guide does not
assume them:

```bash
INSTANCE_ARN=$(aws sso-admin list-instances --region us-east-1 --query 'Instances[0].InstanceArn' --output text)
for ps in $(aws sso-admin list-permission-sets --region us-east-1 --instance-arn "$INSTANCE_ARN" --query 'PermissionSets[]' --output text); do
  name=$(aws sso-admin describe-permission-set --region us-east-1 --instance-arn "$INSTANCE_ARN" --permission-set-arn "$ps" \
         --query 'PermissionSet.Name' --output text)
  [ "$name" = "SMaHT-Deployment-Manager" ] && PERMISSION_SET_ARN=$ps
done
aws sso-admin provision-permission-set --region us-east-1 --instance-arn "$INSTANCE_ARN" \
    --permission-set-arn "$PERMISSION_SET_ARN" --target-type AWS_ACCOUNT --target-id 517723527581
```

The provisioned role keeps its name, `AWSReservedSSO_SMaHT-Deployment-Manager_<suffix>`, as long as
at least one assignment remains.

## Step 4 - check

As the IAM administrator in 517723527581, list the role's policies. The role is under path
`/aws-reserved/sso.amazonaws.com/`.

```bash
ROLE=$(aws iam list-roles --region us-east-1 --path-prefix /aws-reserved/sso.amazonaws.com/ \
       --query "Roles[?starts_with(RoleName, 'AWSReservedSSO_SMaHT-Deployment-Manager_')].RoleName" --output text)
aws iam list-attached-role-policies --region us-east-1 --role-name "$ROLE"   # exactly the three SMaHTInfraDeploy* policies
aws iam list-role-policies --region us-east-1 --role-name "$ROLE"            # AwsSSOInlinePolicy
aws iam simulate-principal-policy --region us-east-1 \
    --policy-source-arn "$(aws iam get-role --region us-east-1 --role-name "$ROLE" --query Role.Arn --output text)" \
    --action-names cloudformation:CreateChangeSet cloudformation:DeleteStack \
    --resource-arns arn:aws:cloudformation:us-east-1:517723527581:stack/c4-iam-main-stack/x
```

## Repository settings and prerequisites (not part of the policy documents)

### Bootstrap steps that need an administrator

These permissions deploy and maintain the `c4-*` stacks. They cannot bootstrap an empty account by
themselves:

- **IAM stack:** apply `c4-iam-main-stack` with administrator credentials. It contains `*DevRole`,
  which these policies protect from modification. Leave `human_access.deploy.*` off; the separate
  opt-in custom role is not needed with this permission set.
- **Secrets and the federator user:** filling application secrets (`setup-remaining-secrets`) and
  creating the S3 federator user's access key are administrator steps. So are removing data-bearing
  resources retained after a failed creation or a stack deletion, and anything else the operator
  guide lists as not covered.

### KMS: set `deploying_iam_user` before the first datastore

The datastore KMS key policy grants `kms:*` only to the principal ARN in `deploying_iam_user`
(`custom/config.json`) and has no account-root statement. IAM permissions alone therefore do not
let this permission set use the key. For this permission set to create the encrypted datastore key
and use it, set this before the first datastore creation:

```json
"deploying_iam_user": "arn:aws:iam::517723527581:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_SMaHT-Deployment-Manager_03ecd9ddf6bd77ba"
```

- **Where the ARN comes from:** a read-only audit of this account on 2026-11-06. Confirm the
  current suffix from a session of this permission set with
  `aws sts get-caller-identity --region us-east-1`
  (`assumed-role/AWSReservedSSO_SMaHT-Deployment-Manager_<suffix>/...`) before writing the config.
- **What it grants:** the role becomes the key's administrator through the key policy. The inline
  policy still denies `kms:ScheduleKeyDeletion` and `kms:DisableKey`, because an explicit IAM deny
  wins. Other key operations, such as direct encrypt/decrypt and grants, come from the key policy.
  That is more than the opt-in custom role receives.
- **Suffix risk:** if all assignments of the permission set in this account are removed, Identity
  Center deletes the role. A new assignment creates a role with a different suffix, and the key
  policy then names a role that no longer exists. Keep a permanent assignment. AWS also recommends
  naming a backup IAM role in key policies; the repository's key policy has one administrator slot,
  so that needs a separate administrator key-policy change.
- **If an administrator principal holds `deploying_iam_user` instead:** this permission set cannot
  use the key. SSE-KMS uploads, such as the Foursight package and encrypted buckets, then need that
  administrator.
- **Existing keys:** for a key that already exists, only its current `deploying_iam_user` can apply
  the change.

### Other things to know

- **Region:** everything runs in us-east-1. The inline policy denies other Regions, except the
  global services it lists.
- **Release command constants:** `identity-swap`'s SMaHT constants (`GLOBAL_ENV_BUCKET`,
  `SMAHT_KMS_KEY_ID`, the alarm ARNs) currently name resources of another account (865557043974).
  For this account the command needs them to name this account's resources; the policies allow the
  generated `<env>-foursight-envs/main.ecosystem` path. `deploy-ecs` needs no change.
- **SRCE / PR97 stacks:** these need `--capabilities CAPABILITY_NAMED_IAM`. Their names fall within
  these policies' `c4-*` scopes, but their resource types are not covered by this repository's
  handler tests.

## How this differs from the opt-in custom role

|  | This bundle (`SMaHT-Deployment-Manager`) | Opt-in `*InfraDeployRole` (`human_access.deploy.*`) |
|---|---|---|
| Who creates the role | IAM Identity Center | CloudFormation, in the IAM stack |
| Authentication and session | Identity Center sign-in and the permission set's session duration (unchanged) | Enumerated principals, MFA at assumption, source identity, one-hour sessions |
| Policies | You create three IAM customer managed policies and one inline policy, and update them by regenerating | Created and updated by the IAM stack |
| KMS access to the datastore key | Through `deploying_iam_user` (above) | Key-policy statements added automatically through the `HumanDeployRoleArn` export |
| Permissions | Identical documents | Identical documents |

Both are trusted-deployer permissions, not a sandbox. See `docs/source/human_access_roles.rst`
("Deployment role") for:
- what the permissions can and cannot do;
- the escalation equivalence;
- builds and image delegation;
- stack-deletion retention;
- the deployment commands.
