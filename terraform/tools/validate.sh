#!/usr/bin/env bash
# Non-interactive schema/lint checks only. Never runs a real-provider plan, apply, import or AWS CLI.
set -uo pipefail
case "${1:-schema}" in
  -h|--help)
    printf 'usage: terraform/tools/validate.sh [schema|lint]\n'
    printf 'schema: fmt, backend-disabled init, validate for every root/module\n'
    printf 'lint: tflint for every root/module; any child failure returns nonzero\n'
    exit 0 ;;
  schema|lint) mode="${1:-schema}" ;;
  *) printf 'error: expected schema or lint\nhelp: terraform/tools/validate.sh --help\n'; exit 2 ;;
esac
root=$(cd "$(dirname "$0")/../.." && pwd -P) || exit 1
cd "$root" || exit 1
# Suppress every ambient AWS credential source and Terraform argument/variable injection.
while IFS= read -r name; do
  case "$name" in AWS_*|TF_VAR_*|TF_CLI_ARGS*) unset "$name" ;; esac
done < <(compgen -e)
export AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true
export TF_IN_AUTOMATION=1 CHECKPOINT_DISABLE=1 TF_CLI_CONFIG_FILE=/dev/null
failed=0
passed=0
check() {
  if "$@" >&2; then passed=$((passed + 1)); return 0; fi
  failed=$((failed + 1))
  printf 'failed: %s\n' "$*"
  return 1
}
if [ "$mode" = schema ]; then
  check terraform fmt -check -recursive terraform || :
fi
search_roots=(terraform/accounts terraform/modules)
[ ! -d terraform/examples ] || search_roots+=(terraform/examples)
if ! mains=$(find "${search_roots[@]}" -name main.tf -not -path '*/.terraform/*'); then
  printf 'error: cannot enumerate Terraform roots\n'
  exit 1
fi
if [ -z "$mains" ]; then
  printf 'error: no Terraform roots found\n'
  exit 1
fi
while IFS= read -r main; do
  dir=$(dirname "$main")
  if [ "$mode" = schema ]; then
    if check terraform "-chdir=$dir" init -backend=false -input=false -no-color; then
      check terraform "-chdir=$dir" validate -no-color || :
    fi
  else
    check tflint "--chdir=$dir" --no-color || :
  fi
done <<< "$mains"
printf 'checks: %s passed, %s failed\n' "$passed" "$failed"
if [ "$failed" -ne 0 ]; then
  printf 'error: offline Terraform %s checks failed\n' "$mode"
  exit 1
fi
printf 'status: offline Terraform %s checks passed (not deployment validation)\n' "$mode"
