from __future__ import annotations

DEFAULT_BUDGET = 16000
DEFAULT_MAX_FILE_BYTES = 262144
DEFAULT_MAX_EXCERPT_BYTES = 65536
DEFAULT_MAX_TOTAL_SCAN_BYTES = 50 * 1024 * 1024
BINARY_SNIFF_BYTES = 8192

# Extensions that represent user-authored source code and must not be
# discarded merely because they live under a package directory named
# "output", "data", "cache", or another generic artifact-like name.
#
# This is intentionally broader than Python. CBL is a local evidence tool
# for heterogeneous repositories; R bridge scripts, shell scripts, SQL,
# frontend code, and typed stubs are source.
CODE_SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyw",
        ".pyi",
        ".r",
        ".rmd",
        ".qmd",
        ".ps1",
        ".psm1",
        ".bat",
        ".cmd",
        ".sh",
        ".sql",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".scss",
        ".html",
    }
)

PARTIAL_IMPLEMENTATION_MESSAGE = (
    "PARTIAL IMPLEMENTATION: this command exists but is not complete in the current milestone."
)

PUBLIC_COMMANDS = (
    "doctor",
    "dump",
    "snapshot",
    "tree",
    "symbols",
    "imports",
    "cli",
    "routes",
    "tests",
    "diff",
    "diffdump",
    "changed",
    "file",
    "symbol",
    "callers",
    "contract",
    "pack",
    "clean",
    "graph",
)

EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_INVALID_ARGUMENTS = 2
EXIT_ROOT_DETECTION_FAILURE = 3
EXIT_PATH_SAFETY_VIOLATION = 4
EXIT_CONTRACT_FAILURE = 5
EXIT_CONTRACT_VIOLATION = 5
EXIT_UNSAFE_OPTION_REJECTED = 6
EXIT_OUTPUT_WRITE_FAILURE = 7

STRONG_PROJECT_MARKERS = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
)

HARD_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".codecontext",
        ".venv",
        "venv",
        "env",
        "ENV",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".ipynb_checkpoints",
        "node_modules",
        "site-packages",
        ".eggs",
    }
)

HARD_EXCLUDED_FILE_PATTERNS = (
    ".env",
    ".env.local",
    ".env.*.local",
    "*.pem",
    "*.key",
    "*.crt",
    "*.cer",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_rsa.pub",
    "id_ed25519",
    "id_ed25519.pub",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.duckdb",
    "*.parquet",
    "*.feather",
    "*.arrow",
    "*.orc",
    "*.avro",
    "*.dbc",
    "*.csv.gz",
    "*.tsv.gz",
    "*.zip",
    "*.7z",
    "*.rar",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.bz2",
    "*.xz",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.bmp",
    "*.tiff",
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.xls",
    "*.xlsx",
    "*.ppt",
    "*.pptx",
    "*.mp4",
    "*.mkv",
    "*.avi",
    "*.mov",
    "*.mp3",
    "*.wav",
    "*.flac",
    "*.exe",
    "*.dll",
    "*.so",
    "*.dylib",
    "*.pyd",
    "*.bin",
    "*.model",
    "*.onnx",
    "*.pt",
    "*.pth",
    "*.ckpt",
)

DEFAULT_INCLUDED_TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyw",
        ".pyi",
        ".r",
        ".R",
        ".Rmd",
        ".qmd",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".jsonl",
        ".md",
        ".rst",
        ".txt",
        ".ini",
        ".cfg",
        ".env.example",
        ".gitignore",
        ".dockerignore",
        ".ps1",
        ".psm1",
        ".bat",
        ".cmd",
        ".sh",
        ".sql",
        ".html",
        ".css",
        ".scss",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".kts",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".lua",
        ".jl",
        ".m",
        ".mm",
        ".swift",
        ".scala",
        ".clj",
        ".ex",
        ".exs",
        ".erl",
        ".hrl",
        ".fs",
        ".fsx",
        ".ml",
        ".mli",
        ".nim",
        ".zig",
        ".hs",
        ".lhs",
        ".pl",
        ".pm",
        ".awk",
        ".sed",
        ".dockerfile",
        ".make",
        ".mk",
        ".cmake",
        ".jinja",
        ".j2",
        ".mustache",
        ".graphql",
        ".proto",
        ".thrift",
        ".csv",
        ".tsv",
    }
)

TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
