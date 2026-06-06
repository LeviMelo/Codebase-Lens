DEFAULT_BUDGET = 16000

PARTIAL_IMPLEMENTATION_MESSAGE = (
    "PARTIAL IMPLEMENTATION: this command exists but is not complete in the current milestone."
)

PUBLIC_COMMANDS = (
    "doctor",
    "snapshot",
    "tree",
    "symbols",
    "imports",
    "cli",
    "routes",
    "tests",
    "diff",
    "changed",
    "file",
    "symbol",
    "callers",
    "contract",
    "pack",
    "clean",
)

EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_INVALID_ARGUMENTS = 2
EXIT_ROOT_DETECTION_FAILURE = 3
EXIT_PATH_SAFETY_VIOLATION = 4
EXIT_CONTRACT_VIOLATION = 5
EXIT_UNSAFE_OPTION_REJECTED = 6
EXIT_OUTPUT_WRITE_FAILURE = 7
