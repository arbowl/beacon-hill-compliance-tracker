"""Tests for the document index (legislative reference database)."""

import uuid

import pytest

from components.models import SummaryInfo, VoteInfo, VoteRecord
from history.artifacts import (
    DocumentIndexEntry,
    DocumentType,
    VoteParticipant,
)
from history.composer import BillArtifactComposer
from history.repository import BillArtifactRepository


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary path for a DuckDB database."""
    path = str(tmp_path / "test_index.db")
    yield path


@pytest.fixture
def repo(tmp_db):
    """Create a repository with a temporary database."""
    return BillArtifactRepository(tmp_db)


class TestDocumentIndexEntry:
    """Test DocumentIndexEntry dataclass."""

    def test_new_creates_valid_entry(self):
        entry = DocumentIndexEntry.new(
            "H100", "194", "J33", DocumentType.SUMMARY
        )
        assert entry.reference_id  # UUID is set
        assert entry.bill_id == "H100"
        assert entry.session == "194"
        assert entry.committee_id == "J33"
        assert entry.document_type == DocumentType.SUMMARY
        assert entry.acquired_date is not None

    def test_new_generates_unique_ids(self):
        e1 = DocumentIndexEntry.new("H100", "194", "J33", DocumentType.SUMMARY)
        e2 = DocumentIndexEntry.new("H100", "194", "J33", DocumentType.SUMMARY)
        assert e1.reference_id != e2.reference_id


class TestVoteParticipant:
    """Test VoteParticipant dataclass."""

    def test_new_creates_valid_participant(self):
        ref_id = str(uuid.uuid4())
        p = VoteParticipant.new(ref_id, "Smith, John", "Yea")
        assert p.participant_id
        assert p.reference_id == ref_id
        assert p.legislator_name == "Smith, John"
        assert p.vote_value == "Yea"
        assert p.chamber is None


class TestRepositorySaveAndLoad:
    """Test saving and loading document index entries."""

    def test_save_and_retrieve_entry(self, repo):
        entry = DocumentIndexEntry.new(
            "H100", "194", "J33", DocumentType.SUMMARY
        )
        entry.source_url = "https://example.com/summary.pdf"
        entry.parser_module = "parsers.summary_hearing_docs_pdf"
        entry.content_hash = "abc123"
        entry.text_length = 1500
        entry.file_format = "pdf"
        entry.bill_title = "An Act relative to testing"
        entry.bill_url = "https://example.com/bill/H100"
        entry.preview = "This is a preview..."

        repo.save_document_index_entry(entry)
        results = repo.get_documents_by_bill("H100", "194")

        assert len(results) == 1
        row = results[0]
        assert row["bill_id"] == "H100"
        assert row["document_type"] == "summary"
        assert row["content_hash"] == "abc123"
        assert row["text_length"] == 1500
        assert row["file_format"] == "pdf"
        assert row["bill_title"] == "An Act relative to testing"

    def test_save_with_vote_participants(self, repo):
        entry = DocumentIndexEntry.new(
            "H200", "194", "J33", DocumentType.VOTES
        )
        entry.content_hash = "def456"
        entry.file_format = "html"

        participants = [
            VoteParticipant.new(entry.reference_id, "Smith, John", "Yea"),
            VoteParticipant.new(entry.reference_id, "Doe, Jane", "Nay"),
        ]
        participants[0].chamber = "House"
        participants[1].chamber = "House"

        repo.save_document_index_entry(entry, participants)
        results = repo.get_documents_by_bill("H200", "194")
        assert len(results) == 1
        assert results[0]["document_type"] == "votes"

    def test_upsert_deduplicates(self, repo):
        """Same (bill_id, session, document_type, content_hash) saves only one row."""
        entry1 = DocumentIndexEntry.new(
            "H100", "194", "J33", DocumentType.SUMMARY
        )
        entry1.content_hash = "same_hash"
        entry1.text_length = 100

        entry2 = DocumentIndexEntry.new(
            "H100", "194", "J33", DocumentType.SUMMARY
        )
        entry2.content_hash = "same_hash"
        entry2.text_length = 200  # Updated value

        repo.save_document_index_entry(entry1)
        repo.save_document_index_entry(entry2)

        results = repo.get_documents_by_bill("H100", "194")
        assert len(results) == 1
        assert results[0]["text_length"] == 200

    def test_multiple_documents_per_bill(self, repo):
        """A bill can have both summary and votes indexed."""
        summary = DocumentIndexEntry.new(
            "H100", "194", "J33", DocumentType.SUMMARY
        )
        summary.content_hash = "hash_s"
        votes = DocumentIndexEntry.new(
            "H100", "194", "J33", DocumentType.VOTES
        )
        votes.content_hash = "hash_v"

        repo.save_document_index_entry(summary)
        repo.save_document_index_entry(votes)

        results = repo.get_documents_by_bill("H100", "194")
        assert len(results) == 2
        types = {r["document_type"] for r in results}
        assert types == {"summary", "votes"}

    def test_get_documents_empty(self, repo):
        results = repo.get_documents_by_bill("H999", "194")
        assert results == []


class TestIndexStats:
    """Test aggregate statistics."""

    def test_stats_empty(self, repo):
        stats = repo.get_index_stats()
        assert stats["total_documents"] == 0
        assert stats["unique_bills"] == 0

    def test_stats_with_data(self, repo):
        for bill_id, doc_type, fmt in [
            ("H100", DocumentType.SUMMARY, "pdf"),
            ("H100", DocumentType.VOTES, "html"),
            ("H200", DocumentType.SUMMARY, "pdf"),
        ]:
            entry = DocumentIndexEntry.new(bill_id, "194", "J33", doc_type)
            entry.content_hash = str(uuid.uuid4())
            entry.file_format = fmt
            repo.save_document_index_entry(entry)

        stats = repo.get_index_stats()
        assert stats["total_documents"] == 3
        assert stats["unique_bills"] == 2
        assert stats["by_type"]["summary"] == 2
        assert stats["by_type"]["votes"] == 1
        assert stats["by_format"]["pdf"] == 2
        assert stats["by_format"]["html"] == 1


class TestComposerDocumentIndex:
    """Test BillArtifactComposer.compose_document_index_entries()."""

    @staticmethod
    def _make_bill():
        from components.models import BillAtHearing
        from datetime import date

        return BillAtHearing(
            bill_id="H100",
            bill_label="H.100",
            bill_url="https://malegislature.gov/Bills/194/H100",
            committee_id="J33",
            hearing_id="12345",
            hearing_date=date(2025, 6, 15),
            hearing_url="https://malegislature.gov/Events/Hearings/Detail/12345",
        )

    def test_compose_with_summary(self):
        bill = self._make_bill()
        summary = SummaryInfo(
            present=True,
            location="Hearing page Documents tab PDF",
            source_url="https://example.com/summary.pdf",
            parser_module="parsers.summary_hearing_docs_pdf",
            content_hash="abc123",
            text_length=1500,
            file_format="pdf",
            full_text="This is the summary text content...",
        )
        votes = VoteInfo(
            present=False,
            location="unknown",
            source_url=None,
            parser_module=None,
        )

        entries, participants = BillArtifactComposer.compose_document_index_entries(
            bill=bill, summary=summary, votes=votes, bill_title="Test Act"
        )

        assert len(entries) == 1
        assert len(participants) == 0
        entry = entries[0]
        assert entry.bill_id == "H100"
        assert entry.session == "194"
        assert entry.document_type == DocumentType.SUMMARY
        assert entry.content_hash == "abc123"
        assert entry.text_length == 1500
        assert entry.file_format == "pdf"
        assert entry.bill_title == "Test Act"
        assert entry.preview == "This is the summary text content..."

    def test_compose_with_votes_and_records(self):
        bill = self._make_bill()
        summary = SummaryInfo(
            present=False, location="unknown", source_url=None, parser_module=None
        )
        votes = VoteInfo(
            present=True,
            location="Bill page Votes tab",
            source_url="https://example.com/votes",
            parser_module="parsers.votes_bill_embedded",
            content_hash="xyz789",
            text_length=800,
            file_format="html",
            full_text="Vote record text...",
            records=[
                VoteRecord(member="Smith, John", vote="Yea"),
                VoteRecord(member="Doe, Jane", vote="Nay"),
            ],
        )

        entries, participants = BillArtifactComposer.compose_document_index_entries(
            bill=bill, summary=summary, votes=votes
        )

        assert len(entries) == 1
        assert entries[0].document_type == DocumentType.VOTES
        assert len(participants) == 2
        assert participants[0].legislator_name == "Smith, John"
        assert participants[0].vote_value == "Yea"
        assert participants[0].chamber == "House"
        assert participants[1].legislator_name == "Doe, Jane"
        # All participants reference the same entry
        assert all(p.reference_id == entries[0].reference_id for p in participants)

    def test_compose_skips_absent_documents(self):
        bill = self._make_bill()
        summary = SummaryInfo(
            present=False, location="unknown", source_url=None, parser_module=None
        )
        votes = VoteInfo(
            present=False, location="unknown", source_url=None, parser_module=None
        )

        entries, participants = BillArtifactComposer.compose_document_index_entries(
            bill=bill, summary=summary, votes=votes
        )

        assert entries == []
        assert participants == []


class TestEnrichedModelRoundtrip:
    """Test that new fields on SummaryInfo/VoteInfo round-trip through to_dict/from_dict."""

    def test_summary_info_roundtrip(self):
        original = SummaryInfo(
            present=True,
            location="test",
            source_url="https://example.com",
            parser_module="parsers.test",
            content_hash="abc123",
            text_length=500,
            file_format="pdf",
            full_text="Full text here",
        )
        data = original.to_dict()
        restored = SummaryInfo.from_dict(data)

        assert restored.content_hash == "abc123"
        assert restored.text_length == 500
        assert restored.file_format == "pdf"
        assert restored.full_text == "Full text here"

    def test_vote_info_roundtrip(self):
        original = VoteInfo(
            present=True,
            location="test",
            source_url="https://example.com",
            parser_module="parsers.test",
            content_hash="def456",
            text_length=800,
            file_format="html",
            full_text="Vote text",
        )
        data = original.to_dict()
        restored = VoteInfo.from_dict(data)

        assert restored.content_hash == "def456"
        assert restored.text_length == 800
        assert restored.file_format == "html"
        assert restored.full_text == "Vote text"

    def test_backward_compatible_from_dict(self):
        """Old cached data without new fields should still deserialize."""
        old_data = {
            "present": True,
            "location": "test",
            "source_url": "https://example.com",
            "parser_module": "parsers.test",
            "needs_review": False,
        }
        summary = SummaryInfo.from_dict(old_data)
        assert summary.content_hash is None
        assert summary.text_length is None
        assert summary.file_format is None
        assert summary.full_text is None


class TestFileFormatOnParsers:
    """Test that all parsers have a valid file_format attribute."""

    def test_all_parsers_have_file_format(self):
        from components.pipeline import SUMMARY_REGISTRY, VOTES_REGISTRY

        valid_formats = {"pdf", "html", "docx"}
        all_parsers = list(SUMMARY_REGISTRY.values()) + list(VOTES_REGISTRY.values())

        assert len(all_parsers) == 14, f"Expected 14 parsers, got {len(all_parsers)}"

        for parser_cls in all_parsers:
            assert hasattr(parser_cls, "file_format"), (
                f"{parser_cls.__name__} missing file_format"
            )
            assert parser_cls.file_format in valid_formats, (
                f"{parser_cls.__name__}.file_format = {parser_cls.file_format!r} "
                f"not in {valid_formats}"
            )
