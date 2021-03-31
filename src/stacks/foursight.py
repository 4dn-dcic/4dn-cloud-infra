from src.stack import C4Stack
from src.part import C4Name, C4Tags, C4Account, C4Repo


class C4FoursightStack(C4Stack):
    # https://github.com/dbmi-bgm/foursight-cgap
    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account, repo: C4Repo):
        super().__init__(description, name, tags, account, parts=[])
