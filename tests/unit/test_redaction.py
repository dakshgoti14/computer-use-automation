from app.safety.redaction import redact_dict, redact_text


def test_redacts_openai_style_api_key():
    text = "using key sk-abcdefghijklmnopqrstuvwx for the call"
    assert "sk-abcdefghijklmnopqrstuvwx" not in redact_text(text)


def test_redacts_google_style_api_key():
    text = "GEMINI_API_KEY=AIzaSyD-fakekeyforredactiontestONLY123456"
    assert "AIzaSyD" not in redact_text(text)


def test_redacts_password_field():
    text = 'login payload: {"username": "op", "password": "hunter2!"}'
    redacted = redact_text(text)
    assert "hunter2" not in redacted


def test_redacts_bearer_token():
    text = "Authorization: Bearer abcdef1234567890.token"
    redacted = redact_text(text)
    assert "abcdef1234567890" not in redacted


def test_redacts_session_cookie():
    text = "Cookie: sessionid=abc123def456ghi789"
    redacted = redact_text(text)
    assert "abc123def456ghi789" not in redacted


def test_redacts_full_member_id_reference():
    text = "member id 5551234 was viewed"
    redacted = redact_text(text)
    assert "5551234" not in redacted


def test_redact_dict_fully_redacts_known_secret_keys():
    payload = {"api_key": "super-secret-value", "note": "ok"}
    redacted = redact_dict(payload)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["note"] == "ok"


def test_redact_dict_recurses_into_nested_structures():
    payload = {"outer": {"password": "hunter2"}, "list": [{"token": "abc"}]}
    redacted = redact_dict(payload)
    assert redacted["outer"]["password"] == "[REDACTED]"
    assert redacted["list"][0]["token"] == "[REDACTED]"


def test_redact_dict_catches_password_shaped_form_field_value():
    # Defense-in-depth: even though the key is "value" (not "password"), a
    # sibling field_type of "password" marks it sensitive. The primary
    # control is that the browser extraction layer never captures password
    # values at all (see app/browser/_extract.js) - this is the backstop.
    payload = {"name": "password", "field_type": "password", "value": "hunter2"}
    redacted = redact_dict(payload)
    assert redacted["value"] == "[REDACTED]"


def test_redaction_is_best_effort_not_perfect():
    # Documented limitation: free-form prose containing a secret-looking
    # value with no recognizable shape/key is NOT guaranteed to be caught.
    text = "the value is qwerty"
    assert redact_text(text) == text
