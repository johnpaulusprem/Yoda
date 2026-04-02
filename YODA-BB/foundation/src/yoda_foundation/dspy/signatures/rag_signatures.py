"""CXO-specific DSPy signatures for RAG, meetings, documents, and insights."""

from __future__ import annotations

from yoda_foundation.dspy.signatures.base_signature import (
    InputField,
    OutputField,
    Signature,
)


class ContextualQA(Signature):
    """Answer questions based on provided context with citations and confidence.

    Inputs are retrieved context passages (with ``[n]`` citation markers) and
    the user's question.  Outputs include step-by-step reasoning, the answer,
    a confidence score, and a list of citation numbers used.
    """

    contexts = InputField(
        description="Retrieved context passages with [n] markers",
        type_hint=str,
    )
    question = InputField(
        description="User's question",
        type_hint=str,
    )

    reasoning = OutputField(
        description="Step-by-step reasoning process",
        type_hint=str,
    )
    answer = OutputField(
        description="Comprehensive answer to the question",
        type_hint=str,
    )
    confidence = OutputField(
        description="Confidence score from 0.0 to 1.0",
        type_hint=str,
    )
    citations = OutputField(
        description="Comma-separated list of citation numbers used, e.g. 1,2,3",
        type_hint=str,
    )


class MeetingExtraction(Signature):
    """Extract structured information from a meeting transcript.

    Takes a full transcript with speaker labels, the meeting subject, and
    participant names.  Produces a summary, action items, decisions,
    key topics, and unresolved questions.
    """

    transcript = InputField(
        description="Full meeting transcript with speaker labels and timestamps",
    )
    subject = InputField(
        description="Meeting subject/title",
    )
    participants = InputField(
        description="Comma-separated list of participant names",
    )

    summary = OutputField(
        description="Concise executive summary of the meeting (2-3 paragraphs)",
    )
    action_items = OutputField(
        description=(
            "JSON array of action items, each with: description, "
            "assigned_to, deadline (if mentioned)"
        ),
    )
    decisions = OutputField(
        description="JSON array of key decisions made during the meeting",
    )
    key_topics = OutputField(
        description="Comma-separated list of main topics discussed",
    )
    unresolved_questions = OutputField(
        description="JSON array of questions or issues left unresolved",
    )


class DocumentSummary(Signature):
    """Summarize a document and extract key information.

    Accepts the full document text and its type, then produces a concise
    summary, key points, and important entities.
    """

    document_text = InputField(
        description="Full text content of the document",
    )
    document_type = InputField(
        description="Type of document (pdf, docx, pptx, html, csv, email)",
    )

    summary = OutputField(
        description="Concise summary of the document",
    )
    key_points = OutputField(
        description="JSON array of key points from the document",
    )
    entities = OutputField(
        description=(
            "JSON array of important entities mentioned "
            "(people, orgs, dates, etc.)"
        ),
    )


class InsightDetection(Signature):
    """Detect conflicts or insights between current and past decisions.

    Compares a current decision against a JSON array of past decisions and
    produces detected conflicts, an overall severity level, and a
    recommended action.
    """

    current_decision = InputField(
        description="The current decision or statement being evaluated",
    )
    past_decisions = InputField(
        description="JSON array of past decisions with context",
    )

    conflicts = OutputField(
        description="JSON array of detected conflicts with past decisions",
    )
    severity = OutputField(
        description="Overall severity: info, warning, or critical",
    )
    recommendation = OutputField(
        description="Recommended action based on the analysis",
    )


__all__ = [
    "ContextualQA",
    "MeetingExtraction",
    "DocumentSummary",
    "InsightDetection",
]
