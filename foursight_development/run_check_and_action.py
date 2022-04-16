import argparse
import json

from foursight_development import development_app as app


EPILOG = __doc__


def run_check_and_action(check, action):
    """Run given check and action with default parameters."""
    check_parameters = {"primary": True}
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


def main():
    parser = argparse.ArgumentParser(
        description="Run a foursight check and action with default parameters",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        "-c",
        help="Check name, formatted as 'check_file/check_name'",
        default="ecs_checks/ecs_status",
    )
    parser.add_argument(
        "--action",
        "-a",
        help="Action name, formatted as 'check_file/action_name'",
        default="",
    )
    args = parser.parse_args()
    run_check_and_action(args.check, args.action)


if __name__ == "__main__":
    main()
