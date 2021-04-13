#!/usr/bin/env python3

import csv
import pickle
import os.path

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# TODO convert most of this script to a GoogUtil class, to be used within 4dn-cloud-infra commands with an --upload flag

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# The ID and range of a sample spreadsheet.
VERSIONED_BUCKETS_SHEET_ID = '1KkyGtiO01_Zr_bOlEMhNT7Y1yDAGiOiiegKC12c4JH0'
VALUE_INPUT_OPTION = 'USER_ENTERED'

# used for testing
'''
VERSIONED_BUCKETS = [
    'elasticbeanstalk-fourfront-staging-blobs',
    'elasticbeanstalk-us-east-1-643366669028'
]
'''
VERSIONED_BUCKETS = [
    'elasticbeanstalk-fourfront-staging-blobs',
    'elasticbeanstalk-fourfront-staging-files',
    'elasticbeanstalk-fourfront-staging-system',
    'elasticbeanstalk-fourfront-staging-wfoutput',
    'elasticbeanstalk-fourfront-webdev-essentials-pack',
    'elasticbeanstalk-fourfront-webdev-files',
    'elasticbeanstalk-fourfront-webprod-blobs',
    'elasticbeanstalk-fourfront-webprod-files',
    'elasticbeanstalk-fourfront-webprod-system',
    'elasticbeanstalk-fourfront-webprod-wfoutput',
    'elasticbeanstalk-us-east-1-643366669028',
    'foursight-envs',
    'jupyterhub-fourfront-notebooks',
    'jupyterhub-fourfront-templates'
]


def out_file_for_vbucket(vbucket):
    """Returns the tsv output file for a given versioned bucket"""
    return 'out/latest_run_for_versioned_bucket_{}.tsv'.format(vbucket)


def get_or_make_creds():
    """Returns a valid google cred for the google sheets scope, either via cache or via valid auth flow"""
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds


def assert_all_files_present():
    """Check that all versioned bucket data exists before proceeding with the upload"""
    for v in VERSIONED_BUCKETS:
        filename = out_file_for_vbucket(v)
        assert os.path.exists(filename) is True, 'filename {} not present'.format(filename)


def main():
    """
    - Fetches list of tsvs to upload
    - Gets Google Sheets creds
    - Uploads each tsv as a separate sheet
    - Uploads summary sheet
    """
    assert_all_files_present()
    creds = get_or_make_creds()
    service = build('sheets', 'v4', credentials=creds)

    # Call the Sheets API
    sheet = service.spreadsheets()

    # Create the needed named ranges in the sheet
    named_ranges = []
    for v in VERSIONED_BUCKETS:
        named_range = {
            'name': v,
            'range': {
                'sheetId': VERSIONED_BUCKETS_SHEET_ID
            }
        }
        named_ranges.append(named_range)

    create_named_ranges_body = {
        'namedRanges': named_ranges
    }
    # TODO create named ranges dynamically (this script works because the named ranges are pre-defined)
    # res = sheet.create(body=create_named_ranges_body).execute()

    # Uploads each tsv's rows as a separate sheet (N.B. bucket name = range name)
    results = []
    for v in VERSIONED_BUCKETS:
        print('Uploading {} to GSheet..'.format(v))
        rows = []
        with open(out_file_for_vbucket(v), newline='') as csvfile:
            reader = csv.reader(csvfile, delimiter='\t', quotechar='|')
            for row in reader:
                rows.append(row)
        body = {
            'values': rows
        }
        result = sheet.values().update(
            spreadsheetId=VERSIONED_BUCKETS_SHEET_ID,
            range=v,
            valueInputOption=VALUE_INPUT_OPTION,
            body=body
        #).execute()
        )   # TODO fix to run the script after debugging summary
        results.append(result)

    print('Uploading Summary...')
    summary_sheet_rows = [[
        'Bucket (see sheet tabs below)',
        'size of extra versions + deleted files',
        'size in GB',
        'size in TB'
    ]]
    for idx, v in enumerate(VERSIONED_BUCKETS):
        row_num = idx + 2  # + 2 => 1 for header, 1 for 0-index conversion
        r = [
            v,
            "=MINUS(\
            SUM('{bucket_name}'!D2:D1000000), \
            SUM('{bucket_name}'!B2:B1000000))".format(bucket_name=v),
            "=DIVIDE(B{},1000000000)".format(row_num),
            "=DIVIDE(B{},1000000000000)".format(row_num)
        ]
        summary_sheet_rows.append(r)
    summary_body = {
        'values': summary_sheet_rows
    }
    summary_result = sheet.values().update(
        spreadsheetId=VERSIONED_BUCKETS_SHEET_ID,
        range='Summary',
        valueInputOption=VALUE_INPUT_OPTION,
        body=summary_body
    ).execute()

    print('All results uploaded, check:')
    print('https://docs.google.com/spreadsheets/d/{}'.format(VERSIONED_BUCKETS_SHEET_ID))
    return summary_result, results


if __name__ == '__main__':
    main()
