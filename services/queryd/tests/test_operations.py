"""Tests for queryd.operations — transport-neutral operations layer.

Covers the GraphQL mutation guard (check_graphql) with all edge cases
previously tested against the tools layer.
"""

from __future__ import annotations

from queryd.operations import _STRIP_PATTERN, check_graphql


# ---------------------------------------------------------------------------
# check_graphql edge cases (ported from test_tools.py)
# ---------------------------------------------------------------------------


def test_check_graphql_clean():
    assert check_graphql("{ Task { _id name } }") is None


def test_check_graphql_query_keyword_ignored():
    """The word 'query' (operation type) is fine."""
    assert check_graphql("query { Task { _id } }") is None


def test_check_graphql_mutation_word_in_string_ok():
    assert check_graphql('{ Captured(filter: { content: { eq: "mutation observed" } }) { _id } }') is None


def test_check_graphql_mutation_in_comment_ok():
    assert check_graphql("# a mutation here would be bad\n{ Task { _id } }") is None


def test_strip_pattern_removes_strings_and_comments():
    q = """# comment line
    query {
        Task(filter: { name: { eq: "mutation inside string" } }) {
            _id
            # inline comment
            name
        }
    }"""
    stripped = _STRIP_PATTERN.sub(" ", q)
    assert "mutation" not in stripped
    assert "comment" not in stripped
    assert "Task" in stripped


def test_check_graphql_mutation_at_document_start_rejected():
    """mutation keyword at start of document is rejected."""
    assert "prohibited keyword" in check_graphql("mutation { _deleteDocuments(x:1) }")


def test_check_graphql_mutation_after_newline_rejected():
    """mutation after leading whitespace is rejected."""
    assert "prohibited keyword" in check_graphql("  \n mutation Foo { x }")


def test_check_graphql_mutation_after_other_operation_rejected():
    """mutation after query in same document is rejected."""
    assert "prohibited keyword" in check_graphql("query A { x } mutation B { y }")


def test_check_graphql_mutation_as_alias_rejected():
    """mutation used as a field alias is now rejected (word-boundary guard)."""
    assert "prohibited keyword" in check_graphql("{ mutation: Task { _id } }")


def test_check_graphql_mutation_as_operation_name_rejected():
    """mutation used as operation name (query mutation { ... }) is rejected."""
    assert "prohibited keyword" in check_graphql("query mutation { Task { _id } }")


def test_check_graphql_mutation_after_comma_bypass_rejected():
    """Batched/comma-separated mutation after a query is rejected."""
    assert "prohibited keyword" in check_graphql(
        "query Q{a},mutation M{x}"
    )


def test_check_graphql_mutation_after_paren_bypass_rejected():
    """Mutation after closing paren is rejected."""
    assert "prohibited keyword" in check_graphql(
        "query{a}\n)mutation Bar{_id}"
    )


def test_check_graphql_mutation_after_comment_bypass_rejected():
    """Mutation placed right after a comment is still rejected."""
    assert "prohibited keyword" in check_graphql(
        "# harmless comment\nmutation Bad{_id}"
    )


def test_check_graphql_mutation_inside_string_literal_passes():
    """The word 'mutation' inside a string literal is stripped → allowed."""
    assert check_graphql(
        '{ Task(filter: { name: { eq: "this is a mutation" } }) { _id } }'
    ) is None


def test_check_graphql_field_named_mutations_passes():
    """Field name 'mutations' (no standalone word boundary) is allowed."""
    assert check_graphql("{ Task { mutations { _id } } }") is None


def test_check_graphql_field_named_mutationRate_passes():
    """Field name 'mutationRate' (no standalone word boundary) is allowed."""
    assert check_graphql("{ Task { mutationRate } }") is None


def test_check_graphql_subscription_rejected():
    """Standalone subscription keyword is rejected."""
    assert "prohibited keyword" in check_graphql("subscription { newTasks { _id } }")
