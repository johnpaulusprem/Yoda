"""Vector-based document classifier using template matching.

Classifies enterprise documents into categories by embedding pre-defined
templates and comparing against input text via cosine similarity. Supports
keyword boosting and confidence-based scoring.

Works entirely in-memory — no external vector store needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from yoda_foundation.rag.embeddings.base_embedder import BaseEmbedder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document categories
# ---------------------------------------------------------------------------

class DocumentCategory(str, Enum):
    """Enterprise document categories."""

    # Business reviews
    MBR = "mbr"
    QBR = "qbr"

    # Delivery & project
    SOW = "sow"
    MSA = "msa"
    STATUS_REPORT = "status_report"
    DELIVERY_DOCUMENT = "delivery_document"
    RISK_DOCUMENT = "risk_document"
    PROJECT_PLAN = "project_plan"

    # Financial
    INVOICE = "invoice"
    FINANCIAL_REPORT = "financial_report"

    # Legal & compliance
    CONTRACT = "contract"
    NDA = "nda"
    COMPLIANCE_DOCUMENT = "compliance_document"

    # Technical
    TECHNICAL_SPEC = "technical_spec"
    ARCHITECTURE_DOCUMENT = "architecture_document"

    # Meeting & communication
    MEETING_AGENDA = "meeting_agenda"
    MEETING_MINUTES = "meeting_minutes"
    MOM = "mom"
    PRESENTATION = "presentation"
    ESCALATION = "escalation"

    # People
    HR_DOCUMENT = "hr_document"
    RESUME = "resume"

    # Catch-all
    GENERAL_DOCUMENT = "general_document"


CATEGORY_LABELS: dict[str, str] = {
    "mbr": "Monthly Business Review",
    "qbr": "Quarterly Business Review",
    "sow": "Statement of Work",
    "msa": "Master Service Agreement",
    "status_report": "Status Report",
    "delivery_document": "Delivery Document",
    "risk_document": "Risk Document",
    "project_plan": "Project Plan",
    "invoice": "Invoice / Receipt",
    "financial_report": "Financial Report",
    "contract": "Contract",
    "nda": "Non-Disclosure Agreement",
    "compliance_document": "Compliance Document",
    "technical_spec": "Technical Specification",
    "architecture_document": "Architecture Document",
    "meeting_agenda": "Meeting Agenda",
    "meeting_minutes": "Meeting Minutes",
    "mom": "Minutes of Meeting (MOM)",
    "presentation": "Presentation",
    "escalation": "Escalation",
    "hr_document": "HR Document",
    "resume": "Resume / CV",
    "general_document": "General Document",
}


# ---------------------------------------------------------------------------
# Templates — realistic examples per category
# ---------------------------------------------------------------------------

DOCUMENT_TEMPLATES: dict[str, list[str]] = {
    "mbr": [
        "Monthly Business Review for January 2026. Revenue: $4.2M vs target $4.0M. Gross margin 42%. Client satisfaction score 4.3/5. Active projects: 12. Resources on bench: 3.",
        "MBR executive summary. Delivery metrics: 95% on-time delivery. SLA compliance 99.2%. Open escalations: 2. New deals in pipeline: $1.5M. Attrition rate: 8%.",
        "Monthly business review deck covering financial performance, delivery health, talent metrics, and client feedback. Includes RAG status for all active engagements.",
        "MBR highlights: Revenue growth 12% YoY. Utilization rate 78%. Customer NPS improved to 62. Three new logos acquired. Two renewals completed.",
        "Monthly review of business operations including P&L walkthrough, headcount analysis, project health dashboard, and risk register summary.",
        "Monthly business review presentation with key performance indicators, revenue trends, margin analysis, and resource utilization breakdown by practice.",
    ],
    "qbr": [
        "Quarterly Business Review Q4 2025. Overall account health: Green. Total contract value: $12M. Quarterly revenue recognized: $3.1M. Strategic initiatives on track.",
        "QBR presentation for Acme Corp. Engagement summary, milestone tracker, resource plan, risk log, and next quarter roadmap. Customer satisfaction survey results included.",
        "Quarterly review covering delivery performance, SLA adherence, innovation initiatives, and value delivered. Includes executive scorecard and trend analysis.",
        "Q3 Business Review. Projects delivered: 4. In-flight: 6. Budget utilization 92%. Change requests: 3 approved, 1 pending. Escalation log attached.",
        "QBR deck with quarterly financial reconciliation, delivery metrics, team performance, client feedback summary, and strategic recommendations for next quarter.",
        "Quarterly business review document including account P&L, project-level health status, resource forecast, and renewal timeline discussion.",
    ],
    "sow": [
        "Statement of Work for Cloud Migration Phase 2. Scope: Migrate 45 applications to Azure. Duration: 6 months. Fixed price: $850K. Deliverables: migration plan, execution, testing, handover.",
        "SOW for Application Development. Sprint-based delivery model. Team composition: 1 PM, 2 Tech Leads, 6 Developers, 2 QA. Rate card attached. Estimated effort: 2,400 person-hours.",
        "Statement of Work: Data Analytics Platform Implementation. Scope includes requirements gathering, data modeling, ETL pipeline development, dashboard creation, and user training.",
        "SOW Amendment #3. Additional scope: API integration with SAP and Salesforce. Incremental cost: $120K. Timeline extension: 4 weeks. Approval signatures required.",
        "Statement of Work for Managed Services. 24x7 support coverage. SLA: P1 response within 15 minutes, P2 within 1 hour. Monthly service credits for SLA breach.",
        "SOW for Digital Transformation Advisory. Phase 1: Assessment (4 weeks). Phase 2: Roadmap (3 weeks). Phase 3: Business case (2 weeks). Deliverables and acceptance criteria defined.",
    ],
    "msa": [
        "Master Service Agreement between TechCorp Inc. and Client Corp. Effective date: January 1, 2026. Governing law: State of Delaware. Term: 3 years with auto-renewal.",
        "MSA covering general terms and conditions, intellectual property rights, confidentiality obligations, indemnification, limitation of liability, and dispute resolution.",
        "Master Service Agreement. Payment terms: Net 30. Insurance requirements: $5M general liability, $2M professional liability. Data protection addendum attached.",
        "MSA amendment adding data processing agreement per GDPR requirements. Updated security obligations, breach notification procedures, and subprocessor management.",
        "Master Service Agreement framework for IT outsourcing engagement. Includes governance structure, escalation matrix, change management process, and exit provisions.",
        "MSA with attached schedules: pricing model, service level definitions, security requirements, business continuity obligations, and key personnel provisions.",
    ],
    "status_report": [
        "Weekly Status Report - Project Phoenix. Overall status: Amber. Sprint 14 completed: 18/22 stories. Blockers: API dependency on external team. Next week: UAT preparation.",
        "Project status update. RAG: Green. Milestones on track. Budget consumed: 65%. Risks: 2 medium. Issues: 1 resolved, 1 pending. Resource changes: 1 addition approved.",
        "Monthly status report for managed services. Incidents: 12 (P1: 0, P2: 3, P3: 9). SLA met: 99.5%. Patching completed: 95%. Change requests: 8 implemented.",
        "Weekly project status. Tasks completed this week: database migration, API testing, security scan. Upcoming: load testing, documentation. Blockers: environment access pending.",
        "Program-level status report across 4 workstreams. Green: Infrastructure, Testing. Amber: Development (2-day delay). Red: None. Steering committee notes attached.",
        "Status report for Q1 delivery. Sprint velocity: 42 points average. Defect backlog: 15 (down from 23). Code coverage: 82%. Release candidate on schedule for March 15.",
        "Bi-weekly status update. Deliverables completed: requirements document, wireframes, data model. In progress: backend development, API design. At risk: third-party integration.",
    ],
    "delivery_document": [
        "Release Notes v3.2.0. New features: Single sign-on integration, bulk import tool, real-time notifications. Bug fixes: 12 resolved. Known issues: 2 documented.",
        "Deployment plan for production release. Pre-deployment checklist, rollback procedure, smoke test cases, monitoring alerts, and communication plan included.",
        "Delivery acceptance certificate. All deliverables per SOW Section 3 have been completed and accepted. Sign-off from client project manager and sponsor.",
        "Go-live readiness assessment. Infrastructure: Ready. Application: Ready. Data migration: Complete. Training: Complete. Support model: Activated. Recommendation: Proceed with go-live.",
        "Transition plan for handover to operations team. Knowledge transfer sessions scheduled. Runbook documentation complete. Support ticket routing configured.",
        "Delivery report summarizing sprint outcomes, demo feedback, defect metrics, and burndown chart. Velocity trending upward. Team capacity stable at 85%.",
        "Cutover plan for system migration. Downtime window: Saturday 2AM-8AM EST. Rollback trigger criteria defined. Communication sent to all stakeholders.",
    ],
    "risk_document": [
        "Risk Register. ID: R-001. Description: Key resource leaving mid-project. Probability: Medium. Impact: High. Mitigation: Cross-training and backup resource identified.",
        "Project risk assessment. Top 5 risks: scope creep, vendor dependency, data quality, timeline pressure, budget overrun. Each with probability, impact, owner, and mitigation plan.",
        "Risk and Issues Log (RAID). 12 risks tracked, 5 issues open, 3 assumptions validated, 4 dependencies monitored. Heatmap and trend analysis included.",
        "Enterprise risk report. Cybersecurity risk: High. Regulatory compliance risk: Medium. Vendor concentration risk: Medium. Business continuity: Low. Actions assigned to risk owners.",
        "Risk mitigation plan for data center migration. Identified 18 risks across infrastructure, application, data, and organizational categories. Contingency budget: $150K.",
        "RAID log update for steering committee. New risk: third-party API rate limits may impact performance. Escalated to High. Mitigation: implement caching layer by Sprint 16.",
        "Risk assessment for new market entry. Financial risk, regulatory risk, competitive risk, operational risk evaluated. Risk appetite framework applied. Board approval required.",
    ],
    "project_plan": [
        "Project plan for ERP implementation. 4 phases: Discovery (8 weeks), Design (12 weeks), Build (16 weeks), Deploy (6 weeks). Total duration: 42 weeks. Budget: $2.4M.",
        "Agile project plan. 12 sprints of 2 weeks each. PI planning every 5 sprints. Release trains aligned with business quarters. Capacity planning and velocity assumptions documented.",
        "Program plan covering 3 workstreams: infrastructure modernization, application refactoring, and process automation. Dependencies mapped. Critical path identified.",
        "Project charter and plan. Objectives, scope, timeline, budget, resource plan, governance structure, communication plan, and quality management approach.",
        "Implementation roadmap. Phase 1: MVP (Q1). Phase 2: Feature expansion (Q2). Phase 3: Integration (Q3). Phase 4: Optimization (Q4). Milestone gates defined.",
        "Resource plan and project timeline. 15 team members across 4 roles. Onboarding schedule, ramp-up curve, and knowledge transfer plan included.",
    ],
    "invoice": [
        "Invoice #INV-2026-0042. Bill to: Acme Corp. For: Consulting services January 2026. Amount: $125,000. Payment terms: Net 30. Due date: February 15, 2026.",
        "Monthly service invoice for managed infrastructure. Fixed fee: $45,000. Variable usage charges: $8,200. Total: $53,200. PO reference: PO-2025-789.",
        "Time and materials invoice. 480 hours x $175/hr = $84,000. Expenses: $3,200 (travel). Total: $87,200. Timesheet approval attached.",
        "Credit note CN-2026-003. Original invoice: INV-2025-0198. Reason: SLA credit for December incident. Amount: -$5,000. Adjusted balance: $40,000.",
        "Milestone-based invoice for Phase 2 completion. Deliverables accepted per SOW. Amount: $200,000 (25% of total contract). Previous payments: $400,000.",
    ],
    "financial_report": [
        "P&L Statement Q4 2025. Revenue: $12.5M. COGS: $7.2M. Gross margin: 42.4%. Operating expenses: $3.8M. EBITDA: $1.5M. Net income: $1.1M.",
        "Annual budget vs actuals report. Revenue 103% of plan. Headcount 97% of plan. Travel expenses 85% of budget. Training spend 120% of allocation.",
        "Financial forecast for FY2026. Projected revenue: $55M (15% growth). Margin target: 40%. Capex budget: $3.2M. Working capital requirements outlined.",
        "Monthly financial dashboard. Revenue by practice, margin by client, DSO (Days Sales Outstanding): 45 days, AR aging analysis, and cash flow projection.",
        "Cost analysis report. Comparison of cloud spend vs on-premise. TCO model over 5 years. ROI calculation. Recommendation: migrate to cloud (18-month payback).",
        "Budget proposal for FY2027. Revenue targets by service line, headcount plan, technology investments, marketing spend, and contingency reserves.",
    ],
    "contract": [
        "Service agreement for IT consulting services. Parties: TechCorp and ClientCo. Services described in Exhibit A. Fees in Exhibit B. Term: 24 months.",
        "Software license agreement. Perpetual license for Enterprise Suite. Annual maintenance: 20% of license fee. Usage: up to 500 named users.",
        "Amendment to existing contract. Extended scope to include mobile application development. Additional consideration: $300K. All other terms remain unchanged.",
        "Subcontractor agreement. Engagement of specialist resources for SAP implementation. Rate: $200/hr. Non-compete clause: 12 months. IP assignment included.",
        "Renewal agreement for managed services contract. Term extended 24 months. Pricing adjustment: 3% annual increase. Updated SLAs per Appendix C.",
    ],
    "nda": [
        "Mutual Non-Disclosure Agreement between Party A and Party B. Purpose: evaluation of potential business relationship. Term: 3 years. Governing law: New York.",
        "Confidential information includes: business plans, financial data, customer lists, technical specifications, proprietary algorithms, and trade secrets.",
        "NDA for M&A due diligence. One-way disclosure. Receiving party obligations: no disclosure to third parties, return or destroy upon request, no reverse engineering.",
        "Non-disclosure agreement covering pre-sales discussions. Confidentiality period: 5 years from disclosure. Carve-outs for publicly available information.",
    ],
    "compliance_document": [
        "SOC 2 Type II audit report. Control objectives evaluated: security, availability, confidentiality. Period: January-December 2025. No exceptions noted.",
        "GDPR Data Protection Impact Assessment. Processing activity: customer analytics. Legal basis: legitimate interest. Risks identified and mitigated.",
        "ISO 27001 Statement of Applicability. 114 controls evaluated. 98 applicable, 16 not applicable with justification. Certification audit scheduled for Q2.",
        "Regulatory compliance checklist for financial services client. Anti-money laundering, KYC, data residency, and cross-border transfer requirements addressed.",
        "Business continuity plan. RPO: 4 hours. RTO: 8 hours. Annual DR test results attached. Incident response team and communication tree documented.",
    ],
    "technical_spec": [
        "Technical specification for REST API v2. Endpoints documented with request/response schemas. Authentication: OAuth 2.0. Rate limiting: 1000 req/min. Pagination supported.",
        "System requirements specification. Functional requirements: 45 items. Non-functional: response time < 200ms, 99.9% uptime, support for 10K concurrent users.",
        "Integration specification for SAP-Salesforce connector. Data mapping, transformation rules, error handling, retry logic, and monitoring requirements defined.",
        "Technical design document for microservices migration. 8 services identified. Communication: async via message queue. Data: eventual consistency. Deployment: Kubernetes.",
        "API specification with OpenAPI 3.0. 28 endpoints across 6 domains. Webhook callbacks for async operations. Versioning strategy: URL path-based.",
    ],
    "architecture_document": [
        "Solution architecture for cloud-native platform. Components: API Gateway, microservices, event bus, data lake, ML pipeline. AWS services mapped to each layer.",
        "Enterprise architecture review. Current state: monolithic on-premise. Target state: cloud-native multi-tenant SaaS. Migration path: strangler fig pattern over 18 months.",
        "Architecture decision record: ADR-042. Context: choosing message broker. Decision: Apache Kafka. Rationale: high throughput, replay capability, ecosystem support.",
        "Infrastructure architecture. 3-tier deployment across 2 availability zones. Auto-scaling groups, load balancers, CDN, WAF, and disaster recovery failover documented.",
        "Data architecture blueprint. Operational data in PostgreSQL. Analytics in Snowflake. Real-time streaming via Kafka. ML feature store in Redis. Data governance policies applied.",
    ],
    "meeting_agenda": [
        "Meeting agenda: Q4 Pipeline Review. Date: Monday 9:00 AM. Attendees: Sales leadership. Topics: pipeline overview, deal updates, forecast adjustments, resource needs.",
        "Steering committee agenda. Items: project status review, budget variance, risk escalations, change request approvals, next quarter planning.",
        "Sprint planning agenda. Review backlog, estimate stories, assign capacity, identify dependencies, agree on sprint goal. Timebox: 2 hours.",
        "Board meeting agenda. CEO update, financial review, strategic initiatives, M&A update, governance items, shareholder resolutions.",
        "Weekly team sync agenda. Standup updates, blockers, cross-team dependencies, announcements, action items from last week.",
    ],
    "meeting_minutes": [
        "Minutes of steering committee meeting held on January 15, 2026. Attendees: 8 members. Decisions: approved Change Request CR-042, deferred budget reallocation to next meeting.",
        "Sprint retrospective notes. What went well: improved velocity, fewer bugs. What to improve: deployment automation, documentation. Action items: 3 assigned.",
        "Board meeting minutes. Resolutions passed: FY2027 budget approved, new board member nominated, dividend policy unchanged. Next meeting: March 15.",
        "Project kickoff meeting minutes. Scope confirmed, team introductions completed, communication plan agreed, first sprint starts Monday. RACI matrix to be finalized by Friday.",
        "Client workshop minutes. Requirements gathered for 3 modules. Priorities agreed. Open questions logged. Follow-up sessions scheduled for next 2 weeks.",
    ],
    "mom": [
        "Minutes of Meeting (MOM). Date: January 20, 2026. Project: Cloud Migration. Attendees: 6 participants. Topics discussed: infrastructure readiness, timeline review, resource allocation.",
        "MOM - Weekly Governance Call. Decisions taken: approved vendor change, deferred database migration by 2 weeks. Action items: 5 new, 3 closed. Next meeting: January 27.",
        "Minutes of Meeting for client steering committee. Agenda items reviewed. Key decisions: budget reallocation approved ($50K from contingency). Escalation on UAT environment resolved.",
        "MOM - Sprint Review. Demo conducted for 4 user stories. Client feedback captured. 2 stories accepted, 2 need rework. Updated backlog priorities agreed.",
        "Minutes of Meeting for vendor coordination call. Integration timeline confirmed. API specifications shared. Testing window agreed: February 1-15. SLA terms finalized.",
        "MOM - Architecture Review Board. Proposed design for event-driven architecture reviewed. Approved with conditions: add circuit breaker pattern, document failure modes. Follow-up in 2 weeks.",
        "Minutes of Meeting. Project kickoff. Scope walkthrough completed. Team introductions done. Governance model agreed. RACI matrix reviewed. Communication cadence: weekly status, bi-weekly steering.",
        "MOM for monthly account review. Account health: Green. Revenue on track. 2 new SOWs in discussion. Client satisfaction: positive. Next MOM scheduled for February.",
    ],
    "escalation": [
        "Escalation Notice - Severity 1. Project: Digital Platform. Issue: Production database outage affecting 5,000 users. Duration: 4 hours. Root cause under investigation. War room activated.",
        "Client escalation: delivery timeline at risk. Original go-live: March 1. Revised estimate: March 15. Reason: third-party API integration delays. Mitigation plan attached.",
        "Escalation to Senior Leadership. Subject: Resource shortage on critical project. Impact: 3 sprint deliverables at risk. Request: approve 2 additional senior developers from bench.",
        "Escalation report. Level: Account Manager. Issue: repeated SLA breaches in managed services (3 incidents in January). Client threatening penalty clause activation. Immediate remediation required.",
        "Delivery escalation. Project: SAP Migration. Blocker: client data freeze extended by 3 weeks. Impact on 4 downstream milestones. Options presented: parallel track, timeline extension, de-scope.",
        "Escalation summary for steering committee. Category: Commercial. Issue: Change requests exceeding 20% of original SOW scope without formal CR approval. Risk: margin erosion.",
        "Escalation: P1 incident unresolved for 48 hours. Service: Payment Gateway. Customer impact: transactions failing for enterprise tier. RCA initiated. Bridge call with CTO scheduled.",
        "Internal escalation memo. Subject: team attrition risk on key account. 3 of 8 team members received external offers. Retention plan needed within 48 hours.",
    ],
    "presentation": [
        "Company overview presentation. 30 slides covering vision, services, case studies, team, and financials. For use in client pitches and RFP responses.",
        "Quarterly all-hands deck. Business update, financial highlights, new client wins, employee recognition, product roadmap, and Q&A.",
        "Sales pitch deck for digital transformation services. Problem statement, proposed approach, team, timeline, pricing, and references.",
        "Technical deep-dive presentation on Kubernetes migration strategy. Architecture diagrams, migration phases, risk mitigation, and demo walkthrough.",
        "Training presentation for new employee onboarding. Company culture, tools and systems, security policies, benefits overview, and first-week checklist.",
    ],
    "hr_document": [
        "Compensation plan for FY2026. Salary bands by level. Variable pay: 10-25% based on role. Stock options vesting schedule. Performance review cycle: bi-annual.",
        "Employee handbook. Policies covering: leave, remote work, code of conduct, anti-harassment, travel and expenses, information security, and social media.",
        "Performance review template. Sections: goals achieved, competency ratings, development areas, career aspirations, manager feedback, and calibration notes.",
        "Organizational chart for Engineering division. VP Engineering, 4 Directors, 12 Managers, 85 individual contributors across platform, product, and SRE teams.",
        "Hiring plan Q1 2026. Open positions: 15. Roles: 6 engineers, 3 product managers, 2 designers, 2 data scientists, 2 sales. Budget impact: $180K/month.",
    ],
    "resume": [
        "John Smith - Senior Software Engineer. 8 years experience. Skills: Python, Java, AWS, Kubernetes, microservices. Education: MS Computer Science, Stanford.",
        "Resume: Project Manager with PMP certification. 12 years in IT consulting. Industries: financial services, healthcare, retail. Managed programs up to $20M.",
        "CV for Data Scientist. PhD in Machine Learning. Publications: 8 peer-reviewed papers. Experience: NLP, computer vision, recommendation systems. Python, PyTorch, TensorFlow.",
        "Profile: Solutions Architect. AWS Certified. 15 years experience designing enterprise systems. Specialization: cloud migration, event-driven architecture, DevOps.",
    ],
    "general_document": [
        "Internal memo regarding office relocation schedule and logistics. Moving date confirmed for March 1. Packing instructions and floor plan attached.",
        "Newsletter draft for Q4 company update. Sections: CEO message, project highlights, new hires, upcoming events, and holiday schedule.",
        "Reference document with standard operating procedures for incident management, change management, and problem management processes.",
    ],
}


# ---------------------------------------------------------------------------
# Keyword boosters per category
# ---------------------------------------------------------------------------

_KEYWORD_BOOSTS: dict[str, dict[str, list[str]]] = {
    "mbr": {
        "strong": ["monthly business review", "mbr", "monthly review", "utilization rate", "attrition", "bench strength"],
        "medium": ["revenue", "margin", "nps", "headcount", "monthly"],
    },
    "qbr": {
        "strong": ["quarterly business review", "qbr", "quarterly review", "account health", "quarterly"],
        "medium": ["scorecard", "engagement summary", "renewal", "strategic"],
    },
    "sow": {
        "strong": ["statement of work", "sow", "scope of work", "deliverables", "person-hours", "rate card"],
        "medium": ["fixed price", "time and materials", "acceptance criteria", "milestones"],
    },
    "msa": {
        "strong": ["master service agreement", "msa", "governing law", "indemnification", "limitation of liability"],
        "medium": ["terms and conditions", "auto-renewal", "intellectual property", "confidentiality"],
    },
    "status_report": {
        "strong": ["status report", "weekly status", "rag status", "sprint", "blockers", "project status"],
        "medium": ["on track", "at risk", "completed", "upcoming", "velocity", "burndown"],
    },
    "delivery_document": {
        "strong": ["release notes", "deployment plan", "go-live", "cutover", "delivery acceptance", "rollback"],
        "medium": ["production", "release", "smoke test", "handover", "transition"],
    },
    "risk_document": {
        "strong": ["risk register", "risk assessment", "raid log", "mitigation plan", "risk matrix", "heatmap"],
        "medium": ["probability", "impact", "residual risk", "risk owner", "contingency"],
    },
    "project_plan": {
        "strong": ["project plan", "project charter", "work breakdown", "critical path", "gantt", "resource plan"],
        "medium": ["milestone", "phase", "workstream", "timeline", "budget"],
    },
    "invoice": {
        "strong": ["invoice", "bill to", "payment terms", "due date", "amount due", "credit note", "purchase order"],
        "medium": ["net 30", "net 60", "total", "remittance", "tax"],
    },
    "financial_report": {
        "strong": ["p&l", "profit and loss", "balance sheet", "cash flow", "ebitda", "financial forecast"],
        "medium": ["revenue", "margin", "budget", "variance", "dso", "working capital"],
    },
    "contract": {
        "strong": ["agreement", "parties", "hereby", "whereas", "term", "executed", "amendment"],
        "medium": ["clause", "obligation", "termination", "renewal", "consideration"],
    },
    "nda": {
        "strong": ["non-disclosure", "nda", "confidential information", "receiving party", "disclosing party"],
        "medium": ["confidentiality", "trade secret", "proprietary", "no disclosure"],
    },
    "compliance_document": {
        "strong": ["soc 2", "iso 27001", "gdpr", "dpia", "audit report", "compliance", "regulatory"],
        "medium": ["controls", "certification", "risk assessment", "data protection", "governance"],
    },
    "technical_spec": {
        "strong": ["technical specification", "api specification", "system requirements", "openapi", "swagger"],
        "medium": ["endpoint", "schema", "authentication", "rate limit", "integration"],
    },
    "architecture_document": {
        "strong": ["architecture", "adr", "solution design", "infrastructure diagram", "data architecture"],
        "medium": ["microservices", "event-driven", "cloud-native", "scalability", "availability zone"],
    },
    "meeting_agenda": {
        "strong": ["agenda", "topics", "attendees", "timebox", "discussion items"],
        "medium": ["meeting", "scheduled", "review", "sync"],
    },
    "meeting_minutes": {
        "strong": ["minutes", "decisions", "action items", "attendees", "resolved", "minutes of meeting"],
        "medium": ["discussed", "agreed", "follow-up", "next steps"],
    },
    "mom": {
        "strong": ["mom", "minutes of meeting", "decisions taken", "action items", "attendees present", "next mom"],
        "medium": ["discussed", "agreed", "governance call", "steering committee", "follow-up"],
    },
    "escalation": {
        "strong": ["escalation", "escalated", "severity 1", "p1 incident", "war room", "blocker", "at risk", "urgent"],
        "medium": ["remediation", "root cause", "mitigation", "impact", "sla breach", "penalty", "unresolved"],
    },
    "presentation": {
        "strong": ["presentation", "slide", "deck", "pptx", "all-hands", "pitch deck"],
        "medium": ["overview", "demo", "walkthrough", "case study"],
    },
    "hr_document": {
        "strong": ["compensation", "employee handbook", "performance review", "hiring plan", "org chart"],
        "medium": ["salary", "benefits", "onboarding", "leave policy", "headcount"],
    },
    "resume": {
        "strong": ["resume", "cv", "curriculum vitae", "work experience", "education", "skills"],
        "medium": ["years experience", "certification", "proficient", "managed", "led"],
    },
    "general_document": {
        "strong": [],
        "medium": [],
    },
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    """Result of a document classification."""

    category: str
    category_label: str
    confidence: float
    suggested_priority: str
    suggested_tags: list[str]


@dataclass
class DetailedClassificationResult(ClassificationResult):
    """Classification result with full scoring details."""

    all_scores: dict[str, float] = field(default_factory=dict)
    top_matches: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Priority / tag suggestion helpers
# ---------------------------------------------------------------------------

_HIGH_PRIORITY_KEYWORDS = [
    "urgent", "asap", "deadline", "overdue", "critical", "escalat",
    "signature required", "approval needed", "action required",
    "p1", "severity 1", "blocker", "showstopper",
]

_MEDIUM_PRIORITY_KEYWORDS = [
    "review", "pending", "follow-up", "at risk", "amber",
    "by end of week", "due date", "reminder",
]

_HIGH_PRIORITY_CATEGORIES = {"msa", "nda", "contract", "risk_document", "compliance_document", "escalation"}
_MEDIUM_PRIORITY_CATEGORIES = {"status_report", "sow", "delivery_document", "invoice", "financial_report", "mom", "mbr", "qbr"}


def _suggest_priority(category: str, text: str) -> str:
    """Suggest priority based on category and keyword signals."""
    text_lower = text.lower()

    # Keyword-based escalation
    for kw in _HIGH_PRIORITY_KEYWORDS:
        if kw in text_lower:
            return "high"

    # Category-based default
    if category in _HIGH_PRIORITY_CATEGORIES:
        for kw in _MEDIUM_PRIORITY_KEYWORDS:
            if kw in text_lower:
                return "high"
        return "medium"

    if category in _MEDIUM_PRIORITY_CATEGORIES:
        return "medium"

    for kw in _MEDIUM_PRIORITY_KEYWORDS:
        if kw in text_lower:
            return "medium"

    return "low"


def _suggest_tags(category: str, text: str) -> list[str]:
    """Suggest tags based on category and detected keywords."""
    tags: list[str] = [CATEGORY_LABELS.get(category, category)]
    text_lower = text.lower()

    # Quarter/period detection
    for q in ["q1", "q2", "q3", "q4"]:
        if q in text_lower:
            tags.append(q.upper())
            break

    for month_kw in ["january", "february", "march", "april", "may", "june",
                     "july", "august", "september", "october", "november", "december"]:
        if month_kw in text_lower:
            tags.append(month_kw.capitalize())
            break

    # Year detection
    for year in ["2024", "2025", "2026", "2027"]:
        if year in text_lower:
            tags.append(f"FY{year}")
            break

    # RAG status
    for rag in ["red", "amber", "green"]:
        if f"status: {rag}" in text_lower or f"rag: {rag}" in text_lower or f"overall status: {rag}" in text_lower:
            tags.append(f"RAG-{rag.capitalize()}")

    # Client detection (simple heuristic)
    if "client" in text_lower or "customer" in text_lower or "account" in text_lower:
        tags.append("Client-Facing")

    if "internal" in text_lower or "all-hands" in text_lower:
        tags.append("Internal")

    return tags


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _apply_keyword_boost(
    query_text: str,
    base_similarity: float,
    category: str,
) -> float:
    """Apply domain-specific keyword boosting."""
    boosts = _KEYWORD_BOOSTS.get(category)
    if not boosts:
        return base_similarity

    query_lower = query_text.lower()

    strong_matches = sum(1 for kw in boosts.get("strong", []) if kw in query_lower)
    medium_matches = sum(1 for kw in boosts.get("medium", []) if kw in query_lower)

    strong_boost = min(0.15, strong_matches * 0.05)
    medium_boost = min(0.10, medium_matches * 0.02)
    total_boost = min(0.20, strong_boost + medium_boost)

    return min(1.0, base_similarity + total_boost)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class DocumentClassifier:
    """Vector-based document classifier using template matching.

    Embeds pre-defined document templates and classifies input text by
    cosine similarity. Operates in-memory — no external vector store needed.

    Args:
        embedder: Any embedder implementing ``embed`` and ``embed_batch``.
        similarity_threshold: Minimum similarity to consider a match.
    """

    def __init__(
        self,
        embedder: BaseEmbedder,
        similarity_threshold: float = 0.3,
    ) -> None:
        self._embedder = embedder
        self._similarity_threshold = similarity_threshold

        # Lazy-initialized on first classify call
        self._template_vectors: np.ndarray | None = None
        self._template_categories: list[str] = []
        self._template_texts: list[str] = []
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Embed all templates on first use."""
        if self._initialized:
            return

        texts: list[str] = []
        categories: list[str] = []
        for category, templates in DOCUMENT_TEMPLATES.items():
            for t in templates:
                texts.append(t)
                categories.append(category)

        logger.info("Embedding %d document classification templates...", len(texts))
        result = await self._embedder.embed_batch(texts)
        self._template_vectors = np.array(result.vectors)
        self._template_categories = categories
        self._template_texts = texts
        self._initialized = True
        logger.info(
            "Document classifier initialized: %d templates, %d dimensions",
            len(texts),
            self._template_vectors.shape[1],
        )

    async def classify(self, text: str, top_k: int = 5) -> ClassificationResult:
        """Classify document text.

        Args:
            text: Document text content (or a representative excerpt).
            top_k: Number of top template matches to consider.

        Returns:
            ClassificationResult with category, confidence, priority, and tags.
        """
        await self._ensure_initialized()
        assert self._template_vectors is not None

        # Embed input
        query_vector = np.array(await self._embedder.embed(text))

        # Compute similarities against all templates
        similarities = np.array([
            _cosine_similarity(query_vector, tv)
            for tv in self._template_vectors
        ])

        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]

        # Score by category with keyword boosting
        category_scores: dict[str, list[float]] = {}
        for idx in top_indices:
            sim = float(similarities[idx])
            if sim < 0.05:
                continue
            cat = self._template_categories[idx]
            boosted = _apply_keyword_boost(text, sim, cat)
            category_scores.setdefault(cat, []).append(boosted)

        if not category_scores:
            return ClassificationResult(
                category="general_document",
                category_label="General Document",
                confidence=0.0,
                suggested_priority="low",
                suggested_tags=_suggest_tags("general_document", text),
            )

        # Weighted confidence per category
        category_confidences: dict[str, float] = {}
        for cat, scores in category_scores.items():
            weighted_avg = sum(s * s for s in scores) / sum(s for s in scores) if scores else 0.0
            max_sim = max(scores)
            count_bonus = min(0.1, len(scores) * 0.02)
            category_confidences[cat] = 0.6 * weighted_avg + 0.3 * max_sim + count_bonus

        # Competitive penalty
        if len(category_confidences) > 1:
            sorted_conf = sorted(category_confidences.values(), reverse=True)
            margin = sorted_conf[0] - sorted_conf[1]
            if margin < 0.15:
                penalty = (0.15 - margin) * 0.5
                for cat in category_confidences:
                    category_confidences[cat] *= (1 - penalty)

        best_cat = max(category_confidences, key=lambda c: category_confidences[c])
        best_conf = category_confidences[best_cat]

        if best_conf < self._similarity_threshold:
            best_cat = "general_document"
            best_conf = category_confidences.get("general_document", best_conf)

        return ClassificationResult(
            category=best_cat,
            category_label=CATEGORY_LABELS.get(best_cat, best_cat),
            confidence=round(best_conf, 4),
            suggested_priority=_suggest_priority(best_cat, text),
            suggested_tags=_suggest_tags(best_cat, text),
        )

    async def classify_with_details(
        self, text: str, top_k: int = 10
    ) -> DetailedClassificationResult:
        """Classify with full scoring details.

        Args:
            text: Document text content.
            top_k: Number of top matches to return.

        Returns:
            DetailedClassificationResult with per-category scores and top matches.
        """
        await self._ensure_initialized()
        assert self._template_vectors is not None

        query_vector = np.array(await self._embedder.embed(text))

        similarities = np.array([
            _cosine_similarity(query_vector, tv)
            for tv in self._template_vectors
        ])

        top_indices = np.argsort(similarities)[::-1][:top_k]

        # Build top matches list
        top_matches: list[dict[str, Any]] = []
        category_scores: dict[str, list[float]] = {}

        for idx in top_indices:
            sim = float(similarities[idx])
            cat = self._template_categories[idx]
            boosted = _apply_keyword_boost(text, sim, cat)
            preview = self._template_texts[idx]
            if len(preview) > 150:
                preview = preview[:150] + "..."

            top_matches.append({
                "category": cat,
                "category_label": CATEGORY_LABELS.get(cat, cat),
                "similarity": round(sim, 4),
                "boosted_similarity": round(boosted, 4),
                "template_preview": preview,
            })

            if sim >= 0.05:
                category_scores.setdefault(cat, []).append(boosted)

        # Confidence calculation
        all_scores: dict[str, float] = {}
        for cat, scores in category_scores.items():
            weighted_avg = sum(s * s for s in scores) / sum(s for s in scores) if scores else 0.0
            max_sim = max(scores)
            count_bonus = min(0.1, len(scores) * 0.02)
            all_scores[cat] = round(0.6 * weighted_avg + 0.3 * max_sim + count_bonus, 4)

        if not all_scores:
            best_cat = "general_document"
            best_conf = 0.0
        else:
            best_cat = max(all_scores, key=lambda c: all_scores[c])
            best_conf = all_scores[best_cat]

        if best_conf < self._similarity_threshold:
            best_cat = "general_document"

        return DetailedClassificationResult(
            category=best_cat,
            category_label=CATEGORY_LABELS.get(best_cat, best_cat),
            confidence=round(best_conf, 4),
            suggested_priority=_suggest_priority(best_cat, text),
            suggested_tags=_suggest_tags(best_cat, text),
            all_scores=all_scores,
            top_matches=top_matches,
        )

    async def classify_file(
        self,
        text: str,
        filename: str | None = None,
        content_type: str | None = None,
        top_k: int = 5,
    ) -> ClassificationResult:
        """Classify using both text content and file metadata.

        Combines vector similarity with filename/extension/MIME type signals
        for improved accuracy across PPT, PDF, DOCX, XLSX, etc.

        Args:
            text: Extracted text content.
            filename: Original filename (e.g. ``"Q4_MBR_Deck.pptx"``).
            content_type: MIME type (e.g. ``"application/pdf"``).
            top_k: Number of template matches to consider.

        Returns:
            ClassificationResult with file-format-aware category and tags.
        """
        # Get base classification from content
        result = await self.classify(text, top_k=top_k)

        # Enrich tags with file format info
        format_tag = _detect_format_tag(filename, content_type)
        if format_tag and format_tag not in result.suggested_tags:
            result.suggested_tags.append(format_tag)

        # Filename-based hint can boost confidence if it matches the category
        if filename:
            filename_hint = _classify_from_filename(filename)
            if filename_hint and filename_hint != result.category:
                # If filename strongly suggests a different category AND
                # the content confidence is low, prefer the filename hint
                if result.confidence < 0.5:
                    result.category = filename_hint
                    result.category_label = CATEGORY_LABELS.get(filename_hint, filename_hint)
                    result.suggested_priority = _suggest_priority(filename_hint, text)

        return result


# ---------------------------------------------------------------------------
# File-format helpers
# ---------------------------------------------------------------------------

_FORMAT_TAGS: dict[str, str] = {
    ".pptx": "PowerPoint",
    ".ppt": "PowerPoint",
    ".pdf": "PDF",
    ".docx": "Word",
    ".doc": "Word",
    ".xlsx": "Excel",
    ".xls": "Excel",
    ".csv": "CSV",
    ".msg": "Outlook Email",
    ".eml": "Email",
    ".txt": "Text",
}

_FILENAME_PATTERNS: dict[str, list[str]] = {
    "mbr": ["mbr", "monthly business review", "monthly_business_review"],
    "qbr": ["qbr", "quarterly business review", "quarterly_business_review"],
    "sow": ["sow", "statement of work", "statement_of_work"],
    "msa": ["msa", "master service agreement", "master_service_agreement"],
    "status_report": ["status report", "status_report", "weekly status", "weekly_status"],
    "mom": ["mom", "minutes of meeting", "minutes_of_meeting", "meeting minutes"],
    "escalation": ["escalation", "escalation_report", "incident_escalation"],
    "risk_document": ["risk register", "risk_register", "raid", "risk assessment"],
    "delivery_document": ["release note", "deployment plan", "cutover", "go-live", "delivery_report"],
    "nda": ["nda", "non-disclosure", "non_disclosure"],
    "invoice": ["invoice", "inv-", "credit note"],
    "resume": ["resume", "cv", "curriculum vitae"],
    "project_plan": ["project plan", "project_plan", "implementation plan"],
}


def _detect_format_tag(filename: str | None, content_type: str | None) -> str | None:
    """Detect a human-readable format tag from filename or MIME type."""
    if filename:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        tag = _FORMAT_TAGS.get(f".{ext}")
        if tag:
            return tag

    if content_type:
        if "presentation" in content_type or "powerpoint" in content_type:
            return "PowerPoint"
        if "spreadsheet" in content_type or "excel" in content_type:
            return "Excel"
        if "wordprocessing" in content_type or "msword" in content_type:
            return "Word"
        if "pdf" in content_type:
            return "PDF"

    return None


def _classify_from_filename(filename: str) -> str | None:
    """Attempt to classify from filename patterns alone."""
    name_lower = filename.lower().replace("-", " ").replace("_", " ")
    for category, patterns in _FILENAME_PATTERNS.items():
        for pattern in patterns:
            if pattern in name_lower:
                return category
    return None
