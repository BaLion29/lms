"""Tests for firnline_core.templates — string.Template substitution only."""

from firnline_core.templates import default_webhook_payload, render


class TestRender:
    def test_substitutes_known_variables(self):
        result = render(
            "Firing $firing_id ($firing_status) at $scheduled_for by trigger $trigger_name",
            firing={
                "@id": "TriggerFiring/f1",
                "status": "pending",
                "scheduled_for": "2026-07-07T12:00:00Z",
                "trigger": "OneShotTrigger/t1",
            },
            subject=None,
            action={"name": "my-action"},
            idempotency_key="action#firing",
        )
        assert "TriggerFiring/f1" in result  # type: ignore[operator]
        assert "pending" in result  # type: ignore[operator]
        assert "2026-07-07T12:00:00Z" in result  # type: ignore[operator]
        assert "t1" in result  # type: ignore[operator]

    def test_unknown_vars_left_intact(self):
        result = render(
            "$unknown_var hello",
            firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
            subject=None,
            action={"name": "a"},
            idempotency_key="k",
        )
        assert result == "$unknown_var hello"

    def test_none_template_returns_none(self):
        result = render(
            None,
            firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
            subject=None,
            action={"name": "a"},
            idempotency_key="k",
        )
        assert result is None

    def test_subject_label_name_fallback(self):
        """name → title → @type → @id chain."""
        # name present
        assert (
            render(
                "$subject_label",
                firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
                subject={"@id": "Reminder/r1", "name": "Bob"},
                action={"name": "a"},
                idempotency_key="k",
            )
            == "Bob"
        )

    def test_subject_label_title_fallback(self):
        assert (
            render(
                "$subject_label",
                firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
                subject={"@id": "Reminder/r1", "title": "Meeting"},
                action={"name": "a"},
                idempotency_key="k",
            )
            == "Meeting"
        )

    def test_subject_label_type_fallback(self):
        assert (
            render(
                "$subject_label",
                firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
                subject={"@id": "Reminder/r1", "@type": "Reminder"},
                action={"name": "a"},
                idempotency_key="k",
            )
            == "Reminder"
        )

    def test_subject_label_id_fallback(self):
        assert (
            render(
                "$subject_label",
                firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
                subject={"@id": "Reminder/r1"},
                action={"name": "a"},
                idempotency_key="k",
            )
            == "Reminder/r1"
        )

    def test_subject_label_none_subject(self):
        assert (
            render(
                "$subject_label",
                firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
                subject=None,
                action={"name": "a"},
                idempotency_key="k",
            )
            == ""
        )

    def test_idempotency_key_and_action_name(self):
        result = render(
            "$action_name - $idempotency_key",
            firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
            subject=None,
            action={"name": "alert"},
            idempotency_key="webhook/notify#f1",
        )
        assert result == "alert - webhook/notify#f1"

    def test_subject_id(self):
        result = render(
            "$subject_id",
            firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": ""},
            subject={"@id": "SomeEntity/e1"},
            action={"name": "a"},
            idempotency_key="k",
        )
        assert result == "SomeEntity/e1"

    def test_trigger_name_from_firing(self):
        result = render(
            "$trigger_name",
            firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": "ScheduleTrigger/my-sched"},
            subject=None,
            action={"name": "a"},
            idempotency_key="k",
        )
        assert result == "my-sched"

    def test_trigger_name_no_slash(self):
        result = render(
            "$trigger_name",
            firing={"@id": "x", "status": "y", "scheduled_for": "z", "trigger": "bare"},
            subject=None,
            action={"name": "a"},
            idempotency_key="k",
        )
        assert result == "bare"


class TestDefaultWebhookPayload:
    def test_produces_expected_shape(self):
        payload = default_webhook_payload(
            firing={"@id": "TriggerFiring/f1", "status": "pending"},
            subject={"@id": "Reminder/r1", "name": "Test"},
            action={"name": "webhook-action"},
            idempotency_key="wa#f1",
            scheduled_for="2026-07-07T12:00:00Z",
        )
        assert payload["firing"] == {"@id": "TriggerFiring/f1", "status": "pending"}
        assert payload["subject"] == {"@id": "Reminder/r1", "name": "Test"}
        assert payload["action_name"] == "webhook-action"
        assert payload["idempotency_key"] == "wa#f1"
        assert payload["scheduled_for"] == "2026-07-07T12:00:00Z"

    def test_subject_none(self):
        payload = default_webhook_payload(
            firing={"@id": "x"},
            subject=None,
            action={"name": "a"},
            idempotency_key="k",
            scheduled_for="t",
        )
        assert payload["subject"] is None
