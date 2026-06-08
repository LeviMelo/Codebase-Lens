from acme_tool.parser import parse_file

def test_parse_file():
    assert parse_file('x = 1')['nodes'] > 0
