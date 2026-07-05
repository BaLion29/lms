"""Seed the database with example inbox documents (idempotent)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from ingestd.models import InboxAudio, InboxAudioStatus, InboxNote, InboxNoteStatus
from ingestd.settings import Settings
from ingestd.tdb import TdbClient, short_iri

logger = structlog.get_logger(__name__)


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def seed(settings: Settings) -> None:
    tdb = TdbClient(
        base_url=settings.tdb_url,
        org=settings.tdb_org,
        db=settings.tdb_db,
        user=settings.tdb_user,
        password=settings.tdb_password,
    )

    try:
        branch = settings.tdb_branch

        # Fetch existing docs for idempotency check
        existing_notes = await tdb.get_documents("InboxNote", branch)
        existing_audios = await tdb.get_documents("InboxAudio", branch)

        existing_note_contents: set[str] = {
            d.get("content", "") for d in existing_notes
        }
        existing_audio_transcriptions: set[str] = {
            d.get("transcription", "") for d in existing_audios
        }

        now = _now()

        to_insert: list[dict[str, object]] = []

        # 1. InboxNote (EN): dentist appointment
        content_1 = (
            "Call the dentist to schedule a cleaning appointment, ideally next week."
        )
        if content_1 not in existing_note_contents:
            note1 = InboxNote(
                content=content_1,
                status=InboxNoteStatus.NEW,
                created_at=now,
                updated_at=now,
            )
            to_insert.append(note1.to_tdb())
            logger.info("seeding_inbox_note", content=content_1[:60])
        else:
            logger.info("inbox_note_already_exists", content=content_1[:60])

        # 2. InboxNote (DE): Mietvertrag
        content_2 = "Ich muss bis Freitag den Mietvertrag unterschreiben und an Anna Meier schicken."
        if content_2 not in existing_note_contents:
            note2 = InboxNote(
                content=content_2,
                status=InboxNoteStatus.NEW,
                created_at=now,
                updated_at=now,
            )
            to_insert.append(note2.to_tdb())
            logger.info("seeding_inbox_note", content=content_2[:60])
        else:
            logger.info("inbox_note_already_exists", content=content_2[:60])

        # 3. InboxAudio (DE): hiking memo
        transcription = "Erinnerung: nächsten Samstag um zehn Uhr Wanderung zur Rotondohütte mit Ben."
        if transcription not in existing_audio_transcriptions:
            audio = InboxAudio(
                file_name="memo-042.m4a",
                file_path="/inbox/memo-042.m4a",
                transcription=transcription,
                recorded_at=now,
                status=InboxAudioStatus.TRANSCRIBED,
                created_at=now,
                updated_at=now,
            )
            to_insert.append(audio.to_tdb())
            logger.info("seeding_inbox_audio", transcription=transcription[:60])
        else:
            logger.info("inbox_audio_already_exists", transcription=transcription[:60])

        if to_insert:
            ids = await tdb.insert_documents(
                to_insert,
                branch=branch,
                message="ingestd seed: example inbox documents",
            )
            for doc_id in ids:
                print(f"  Inserted: {short_iri(doc_id)}")
        else:
            print("All seed documents already exist – nothing inserted.")

    finally:
        await tdb.aclose()


def main() -> None:
    _configure_logging()

    settings = Settings()  # type: ignore[call-arg]
    try:
        asyncio.run(seed(settings))
    except Exception:
        logger.exception("seed_failed")
        raise SystemExit(1) from None

    print("Seed complete.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
