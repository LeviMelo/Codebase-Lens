import argparse
from acme_tool.parser import parse_file
from acme_tool.reports import write_report

def run_analyze(text: str) -> str:
    data = parse_file(text)
    return write_report(data)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command')
    analyze = sub.add_parser('analyze')
    analyze.set_defaults(handler=run_analyze)
    return parser
