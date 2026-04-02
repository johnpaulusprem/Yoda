"""Golden QA test cases for evaluating the RAG pipeline.

Each :class:`EvalCase` represents a realistic enterprise question that the
RAG pipeline should be able to answer from ingested meeting transcripts,
documents, and other organisational content.
"""

from __future__ import annotations

from yoda_foundation.rag.evaluation.evaluator import EvalCase

GOLDEN_QA_CASES: list[EvalCase] = [
    # --- Factual (single-source, direct lookup) ---
    EvalCase(
        question="What was the Q4 pipeline target?",
        expected_answer="The Q4 pipeline target is $5.5M.",
        expected_sources=["Q4 Pipeline Model"],
        category="factual",
    ),
    EvalCase(
        question="What is the current ARR for the EMEA region?",
        expected_answer="EMEA ARR currently stands at $2.1M.",
        expected_sources=["Regional Revenue Dashboard"],
        category="factual",
    ),
    EvalCase(
        question="When is the product launch scheduled?",
        expected_answer="The product launch is scheduled for March 15, 2026.",
        expected_sources=["Product Launch Timeline"],
        category="factual",
    ),
    EvalCase(
        question="Who is the executive sponsor for Project Atlas?",
        expected_answer="Sarah Chen is the executive sponsor for Project Atlas.",
        expected_sources=["Project Atlas Charter"],
        category="factual",
    ),
    EvalCase(
        question="What was the customer satisfaction score in Q3?",
        expected_answer="The Q3 CSAT score was 87%.",
        expected_sources=["Q3 Customer Satisfaction Report"],
        category="factual",
    ),
    # --- Reasoning (inference, cause-effect, decision rationale) ---
    EvalCase(
        question="What decisions were made about TechFlow in the pipeline review?",
        expected_answer=(
            "The team decided to deprioritize TechFlow until legal clears "
            "the IP concerns. Follow-up scheduled for end of month."
        ),
        expected_sources=["Pipeline Review Summary"],
        category="reasoning",
    ),
    EvalCase(
        question="Why was the cloud migration timeline extended?",
        expected_answer=(
            "The timeline was extended by 6 weeks due to unexpected "
            "compliance requirements from the security audit."
        ),
        expected_sources=["Cloud Migration Status Update"],
        category="reasoning",
    ),
    EvalCase(
        question="What are the risks identified for the Q1 hiring plan?",
        expected_answer=(
            "Key risks include budget constraints from finance, "
            "competitive market for senior engineers, and potential "
            "org restructuring in April."
        ),
        expected_sources=["Q1 Hiring Plan", "Budget Review Notes"],
        category="reasoning",
    ),
    # --- Multi-document (answer requires combining information) ---
    EvalCase(
        question="How does the current pipeline compare to last quarter's target?",
        expected_answer=(
            "Current pipeline is at $4.8M against a Q3 target of $4.2M "
            "and Q4 target of $5.5M, representing a 14% increase QoQ."
        ),
        expected_sources=["Q3 Pipeline Model", "Q4 Pipeline Model"],
        category="multi-doc",
    ),
    EvalCase(
        question="What action items came from both the design review and sprint retro?",
        expected_answer=(
            "From the design review: update the API schema and schedule "
            "a follow-up with the platform team. From the sprint retro: "
            "improve test coverage to 80% and adopt trunk-based development."
        ),
        expected_sources=["Design Review Summary", "Sprint Retrospective Notes"],
        category="multi-doc",
    ),
    EvalCase(
        question="Summarize the budget allocation across all departments for Q4.",
        expected_answer=(
            "Engineering: $3.2M (40%), Sales: $2.4M (30%), "
            "Marketing: $1.2M (15%), Operations: $0.8M (10%), "
            "Other: $0.4M (5%). Total Q4 budget is $8M."
        ),
        expected_sources=["Q4 Budget Plan", "Department Allocation Spreadsheet"],
        category="multi-doc",
    ),
    # --- Meeting-specific (transcript-based) ---
    EvalCase(
        question="What did the CEO say about international expansion in the all-hands?",
        expected_answer=(
            "The CEO announced plans to expand into Southeast Asia in H2 2026, "
            "starting with Singapore as the regional hub."
        ),
        expected_sources=["All-Hands Meeting Transcript"],
        category="meeting",
    ),
    EvalCase(
        question="Who raised concerns about the vendor contract renewal?",
        expected_answer=(
            "David Park from Legal raised concerns about the auto-renewal "
            "clause and recommended renegotiating the SLA terms."
        ),
        expected_sources=["Vendor Review Meeting Transcript"],
        category="meeting",
    ),
    # --- Edge cases ---
    EvalCase(
        question="What is the company policy on remote work?",
        expected_answer=(
            "The company follows a hybrid model: 3 days in office, "
            "2 days remote. Fully remote is available for roles "
            "approved by the VP and HR."
        ),
        expected_sources=["Employee Handbook", "HR Policy Update"],
        category="policy",
    ),
    EvalCase(
        question="Are there any pending compliance issues?",
        expected_answer=(
            "Two pending items: SOC 2 Type II audit scheduled for April, "
            "and GDPR data processing agreement renewal for EU customers "
            "due by end of Q1."
        ),
        expected_sources=["Compliance Tracker", "Q1 Risk Register"],
        category="compliance",
    ),
]

__all__ = [
    "GOLDEN_QA_CASES",
]
