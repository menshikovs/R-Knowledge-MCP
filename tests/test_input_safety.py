import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.input_safety import contains_credential_like_text
from cran_knowledge_mcp.prompt_intelligence import PromptIntelligence
from cran_knowledge_mcp.prompt_intelligence.quality import validate_prompt
from cran_knowledge_mcp.technology_recommendation import validate_recommendation_inputs


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer synthetic-token-value",
        "Bearer synthetic-token-value",
        "api_key=synthetic-api-key-value",
        "OPENAI_API_KEY=synthetic-api-key-value",
        "x-api-key: synthetic-api-key-value",
        "ACCESS_TOKEN: synthetic-access-token",
        "GOOGLE_ACCESS_TOKEN=synthetic-access-token",
        "https://synthetic-user:synthetic-password@example.test/path",
        "https://example.test/callback?access_token=synthetic-access-token",
        "sk-proj-synthetic-key-value-123456",
    ],
)
def test_common_credential_forms_are_detected(value):
    assert contains_credential_like_text(value)


@pytest.mark.parametrize(
    "value",
    [
        "Authorization headers protect requests.",
        "Set an API key before deploying this service.",
        "The access token is supplied by the user's identity provider.",
        "https://example.test/docs?page=2",
        "Создать отчёт и сохранить исходное требование без перевода.",
    ],
)
def test_ordinary_english_urls_and_russian_text_are_preserved(value):
    assert not contains_credential_like_text(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("objective", "Authorization: Bearer synthetic-token-value"),
        ("requirements", "access_token=synthetic-access-token"),
        ("existing_stack", "https://user:secret@example.test"),
        ("preferences", "api_key=synthetic-api-key-value"),
    ],
)
def test_recommendation_validator_rejects_credentials_without_echoing(field, value):
    inputs = {
        "objective": "Build a safe R project",
        "project_type": "other",
        "requirements": [],
        "existing_stack": [],
        "deployment_target": None,
        "preferences": {"prefer": [], "exclude": []},
    }
    if field == "preferences":
        inputs[field] = {"prefer": [value], "exclude": []}
    elif field in {"requirements", "existing_stack"}:
        inputs[field] = [value]
    else:
        inputs[field] = value

    with pytest.raises(KnowledgeError) as error:
        validate_recommendation_inputs(**inputs)

    assert error.value.code == "sensitive_input"
    assert value not in str(error.value)


def test_prompt_quality_uses_the_shared_credential_detector_without_echoing():
    value = "Authorization: Bearer synthetic-token-value"

    result = validate_prompt(f"Build an R service. {value}")

    finding = next(item for item in result["findings"] if item["code"] == "possible_secret")
    assert value not in finding["message"]


@pytest.mark.asyncio
async def test_prompt_intelligence_rejects_credential_before_returning_prompt_text():
    value = "Authorization: Bearer synthetic-token-value"

    with pytest.raises(KnowledgeError) as error:
        await PromptIntelligence(None).build_r_prompt(
            f"Build an R service. {value}", composition_mode="single"
        )

    assert error.value.code == "sensitive_input"
    assert value not in str(error.value)


def test_enhancement_output_with_credential_is_rejected_before_copying():
    value = "Authorization: Bearer synthetic-token-value"

    assert not PromptIntelligence._validate_enhanced(
        f"Build an R service. {value}",
        "Build an R service.",
        [],
        [],
        [],
    )


@pytest.mark.parametrize(
    "value",
    [
        'con <- dbConnect(RPostgres::Postgres(), password = Sys.getenv("PGPASS"))',
        'password = keyring::key_get("warehouse")',
        "password = input$password",
        "token = gargle::token_fetch()",
        "api_key: Sys.getenv ('API_KEY')",
    ],
)
def test_runtime_secret_lookups_are_not_treated_as_embedded_credentials(value):
    assert not contains_credential_like_text(value)


@pytest.mark.parametrize(
    "value",
    ['password = "hunter22"', "password=hunter22", "token: synthetic-token-value"],
)
def test_literal_credential_assignments_are_still_detected(value):
    assert contains_credential_like_text(value)
