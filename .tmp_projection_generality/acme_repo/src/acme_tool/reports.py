import json

def write_report(data: dict[str, int]) -> str:
    return json.dumps(data, sort_keys=True)
