import csv
import pickle
import os.path

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


class GoogUtil:
    # If modifying these scopes, delete the file token.pickle.
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # The ID and range of a sample spreadsheet.
    VERSIONED_BUCKETS_SHEET_ID = '1KkyGtiO01_Zr_bOlEMhNT7Y1yDAGiOiiegKC12c4JH0'
    VALUE_INPUT_OPTION = 'USER_ENTERED'

