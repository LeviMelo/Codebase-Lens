import ast

def parse_file(text: str) -> dict[str, int]:
    tree = ast.parse(text)
    return {'nodes': len(list(ast.walk(tree)))}
