import json
from typing import Dict

def json_formatter(data: Dict):
    return json.dumps(data, indent=4, ensure_ascii=False)

def pretty_printer(data: Dict):
    print(json_formatter(data))