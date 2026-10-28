"""Recall/precision of the credential heuristics on a small hand-made set (illustrative, not a benchmark)."""
from cran_knowledge_mcp.input_safety import contains_credential_like_text as pi_detect
from cran_knowledge_mcp.providers.context7 import safe_query

POSITIVE = [
    "password = hunter2hunter2",
    "my api_key: AKIAABCDEFGHIJKLMNOP",
    "ghp_" + "a" * 36,
    "Authorization: Bearer abcdef1234567890",
    "token=abcd1234efgh",
    "postgres://admin:S3cretPass@db.example.com/prod",
    "https://api.example.com/v1?api_key=abcd1234efgh5678",
    "sk-" + "A1b2C3d4" * 4,
    "client_secret: 'wJalrXUtnFEMI/K7MDENG'",
]
NEGATIVE_R_CODE = [
    'key <- Sys.getenv("API_KEY")',
    "password <- rstudioapi::askForPassword()",
    "con <- dbConnect(RPostgres::Postgres(), password = Sys.getenv('PGPASSWORD'))",
    "Explain how token refresh works in httr2",
    "How do I hash a password with sodium?",
]
EVASIONS = [
    "p a s s w o r d = hunter2hunter2",
    "pass = hunter2hunter2",
    "pwd=hunter2hunter2",
    "the key is AKIA" + "ABCDEFGHIJKLMNOP"[:8] + " " + "ABCDEFGH",
    "secret​=hunter2hunter2",
    "ZXhhbXBsZS1iYXNlNjQtc2VjcmV0LXRva2Vu (base64 of a secret)",
]
print("== prompt-intelligence detector (input_safety.contains_credential_like_text)")
print(" positives detected:", sum(pi_detect(x) for x in POSITIVE), "/", len(POSITIVE))
print(" non-secret R code / questions flagged:", [x[:40] for x in NEGATIVE_R_CODE if pi_detect(x)])
print(" evasions NOT detected:", [x[:40] for x in EVASIONS if not pi_detect(x)])
print("== context7 safe_query redaction")
print(" positives left unredacted:", [x[:40] for x in POSITIVE if "[REDACTED]" not in safe_query(x)])
print(" benign text altered:", [x[:40] for x in NEGATIVE_R_CODE if "[REDACTED]" in safe_query(x)])
print(" evasions left unredacted:", [x[:40] for x in EVASIONS if "[REDACTED]" not in safe_query(x)])
