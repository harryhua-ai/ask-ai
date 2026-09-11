"""Transport hardening: GraphQL variable inlining must be injection-safe."""
import pytest

from project_automation.queries import build_query


class TestVariableInlining:
    def test_simple_substitution(self):
        q = build_query("query { user(login: $login) { login } }", login="harryhua-ai")
        assert '"harryhua-ai"' in q
        assert "$login" not in q

    def test_int_substitution(self):
        q = build_query("query { p(number: $n) { title } }", n=2)
        assert "number: 2" in q

    def test_quotes_and_backslashes_escaped(self):
        evil = 'x" } } ) { deleteProject(input:"1") } #\\'
        q = build_query("query { q(v: $v) }", v=evil)
        import json
        # the value must be embedded as ONE escaped JSON string literal
        assert json.dumps(evil) in q
        assert q.count("{ q(v:") == 1

    def test_newlines_escaped(self):
        q = build_query("query { q(v: $v) }", v="line1\nline2")
        assert "line1\\nline2" in q

    def test_unknown_variable_is_config_error(self):
        from project_automation.errors import ConfigError
        with pytest.raises(ConfigError):
            build_query("query { q(v: $known) }", unknown="x")

    def test_dollar_sign_in_value_not_treated_as_variable(self):
        q = build_query("query { q(v: $v) }", v="cost $100 and ${brace}")
        assert "$100" in q  # value text preserved inside the literal
