import json

import app

check = "wrangler_checks/item_counts_by_type"
check_parameters = {"primary": True}
action = ""
stage = "prod"

app.set_stage(stage)
app_utils = app.AppUtils()
connection = app_utils.init_connection(app.DEFAULT_ENV)

check_run = app_utils.check_handler.run_check_or_action(
    connection, check, check_parameters
)
result = json.dumps(check_run, indent=4)
print(result)

check_uuid = check_run["kwargs"]["uuid"]
action_parameters = {"check_name": check.split("/")[1], "called_by": check_uuid}

if action:
    action_run = app_utils.check_handler.run_check_or_action(
        connection, action, action_parameters
    )
    result = json.dumps(action_run, ident=4)
    print(result)
