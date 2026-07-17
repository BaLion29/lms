"""Tests for DeliberationsIndexerPlugin."""
from __future__ import annotations
from firnline_ext_deliberation.indexer import DeliberationsIndexerPlugin, plugin


class TestIndexerPluginMetadata:
    def test_name(self):
        assert plugin.name == "deliberation_indexer"

    def test_requires(self):
        assert len(plugin.requires) == 1
        req = plugin.requires[0]
        assert req.name == "deliberation"
        assert req.range == ">=0.1.0 <0.2.0"

    def test_indexed_classes(self):
        assert plugin.indexed_classes() == ["Decision", "Problem", "Question"]


class TestEntityTextDecision:
    def test_full_decision(self):
        doc = {
            "@type": "Decision",
            "title": "Use PostgreSQL",
            "decision": "We will use PostgreSQL as the primary database",
            "consequences": "Need to migrate existing data",
        }
        assert plugin.entity_text(doc) == (
            "Use PostgreSQL"
            " — We will use PostgreSQL as the primary database"
            " — Need to migrate existing data"
        )

    def test_decision_minimal(self):
        doc = {
            "@type": "Decision",
            "title": "Use PostgreSQL",
            "decision": "We will use PostgreSQL",
        }
        assert plugin.entity_text(doc) == (
            "Use PostgreSQL — We will use PostgreSQL"
        )

    def test_decision_title_only(self):
        doc = {
            "@type": "Decision",
            "title": "Use PostgreSQL",
        }
        assert plugin.entity_text(doc) == "Use PostgreSQL"

    def test_decision_context_not_in_text(self):
        doc = {
            "@type": "Decision",
            "title": "Use PostgreSQL",
            "decision": "We will use PostgreSQL",
            "context": ["urn:example:context:1", "urn:example:context:2"],
        }
        text = plugin.entity_text(doc)
        assert "urn:example:context" not in text
        assert text == "Use PostgreSQL — We will use PostgreSQL"

    def test_decision_with_consequences_only(self):
        doc = {
            "@type": "Decision",
            "title": "Use PostgreSQL",
            "consequences": "Need to migrate data",
        }
        assert plugin.entity_text(doc) == (
            "Use PostgreSQL — Need to migrate data"
        )

    def test_decision_options_not_in_text(self):
        doc = {
            "@type": "Decision",
            "title": "Use PostgreSQL",
            "decision": "We will use PostgreSQL",
            "options": [{"name": "Use MySQL", "pros": [], "cons": []}],
        }
        text = plugin.entity_text(doc)
        assert "MySQL" not in text
        assert text == "Use PostgreSQL — We will use PostgreSQL"

    def test_decision_empty_fields_not_appended(self):
        doc = {
            "@type": "Decision",
            "title": "Use PostgreSQL",
            "decision": "",
            "consequences": None,
        }
        assert plugin.entity_text(doc) == "Use PostgreSQL"


class TestEntityTextProblem:
    def test_full_problem(self):
        doc = {
            "@type": "Problem",
            "title": "Slow queries",
            "description": "Queries are taking too long on large tables",
            "impact": "Users experience timeouts",
        }
        assert plugin.entity_text(doc) == (
            "Slow queries"
            " — Queries are taking too long on large tables"
            " — Users experience timeouts"
        )

    def test_problem_minimal(self):
        doc = {
            "@type": "Problem",
            "title": "Slow queries",
        }
        assert plugin.entity_text(doc) == "Slow queries"

    def test_problem_with_description_only(self):
        doc = {
            "@type": "Problem",
            "title": "Slow queries",
            "description": "Queries are taking too long",
        }
        assert plugin.entity_text(doc) == (
            "Slow queries — Queries are taking too long"
        )

    def test_problem_with_impact_only(self):
        doc = {
            "@type": "Problem",
            "title": "Slow queries",
            "impact": "Users experience timeouts",
        }
        assert plugin.entity_text(doc) == (
            "Slow queries — Users experience timeouts"
        )


class TestEntityTextQuestion:
    def test_full_question(self):
        doc = {
            "@type": "Question",
            "question": "What database should we use?",
            "answer": "PostgreSQL is the best fit",
        }
        assert plugin.entity_text(doc) == (
            "What database should we use? — PostgreSQL is the best fit"
        )

    def test_question_minimal(self):
        doc = {
            "@type": "Question",
            "question": "What database should we use?",
        }
        assert plugin.entity_text(doc) == "What database should we use?"

    def test_question_no_answer(self):
        doc = {
            "@type": "Question",
            "question": "What database?",
            "answer": None,
        }
        assert plugin.entity_text(doc) == "What database?"


class TestEntityTextFallback:
    def test_unknown_type_uses_title(self):
        doc = {
            "@type": "UnknownType",
            "title": "Some title",
            "question": "Some question",
        }
        assert plugin.entity_text(doc) == "Some title"

    def test_unknown_type_uses_question(self):
        doc = {
            "@type": "UnknownType",
            "question": "Some question",
        }
        assert plugin.entity_text(doc) == "Some question"

    def test_unknown_type_empty(self):
        doc = {"@type": "UnknownType"}
        assert plugin.entity_text(doc) == ""

    def test_missing_type_uses_title(self):
        doc = {"title": "Some title"}
        assert plugin.entity_text(doc) == "Some title"


class TestEntityName:
    def test_decision_name(self):
        doc = {"@type": "Decision", "title": "Use PostgreSQL"}
        assert plugin.entity_name(doc) == "Use PostgreSQL"

    def test_problem_name(self):
        doc = {"@type": "Problem", "title": "Slow queries"}
        assert plugin.entity_name(doc) == "Slow queries"

    def test_question_name(self):
        doc = {"@type": "Question", "question": "What DB?"}
        assert plugin.entity_name(doc) == "What DB?"

    def test_missing_fields(self):
        doc = {}
        assert plugin.entity_name(doc) == ""


class TestEntityAliases:
    def test_decision_aliases(self):
        doc = {"@type": "Decision", "title": "T"}
        assert plugin.entity_aliases(doc) == ["T"]

    def test_problem_aliases(self):
        doc = {"@type": "Problem", "title": "P"}
        assert plugin.entity_aliases(doc) == ["P"]

    def test_question_aliases(self):
        doc = {"@type": "Question", "question": "Q"}
        assert plugin.entity_aliases(doc) == ["Q"]

    def test_aliases_empty_when_no_label(self):
        doc = {}
        assert plugin.entity_aliases(doc) == []


class TestModuleLevelPlugin:
    def test_plugin_is_DeliberationsIndexerPlugin(self):
        assert isinstance(plugin, DeliberationsIndexerPlugin)

    def test_plugin_name(self):
        assert plugin.name == "deliberation_indexer"
