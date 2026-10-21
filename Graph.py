import os
from typing import Any, TypedDict

from dotenv import load_dotenv
from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

load_dotenv()


class EmailDetails(BaseModel):
    email_subject: str
    email_body: str


class AgentState(TypedDict, total=False):
    user_id: str
    role: str
    campaign_id: str | None
    campaign_name: str | None
    profile: dict[str, Any]
    brief: dict[str, Any]
    variables: dict[str, str]
    project_catalog: dict[str, str]
    projects: list[str]
    web_searched_info: list[dict[str, Any]]
    summarised_company_info: str
    written_email_details: EmailDetails
    company_name: str
    recipient_name: str
    recipient_email: str
    final_email_status: bool
    email_from: str
    details: str
    email_response: dict[str, Any] | None
    db_id: str
    deliverability_risk: dict[str, Any] | None
    deliverability_history: list[dict[str, Any]]
    outreach_status: str
    quota_blocked: bool


class OutreachInput(BaseModel):
    user_id: str
    company_name: str = ""
    recipient_name: str = ""
    recipient_email: str
    email_from: str
    details: str = ""
    projects: list[str] = Field(default_factory=list)
    role: str = "student"
    campaign_id: str | None = None
    campaign_name: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    brief: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, str] = Field(default_factory=dict)
    project_catalog: dict[str, str] = Field(default_factory=dict)


def campaign_type_for(agent_state: AgentState) -> str:
    return "campaign" if agent_state.get("role") == "campaigner" else "outreach"


def _uses_template(agent_state: AgentState) -> bool:
    return (agent_state.get("brief") or {}).get("writing_mode") == "template"


def web_search_agent(agent_state: AgentState) -> AgentState:
    brief = agent_state.get("brief") or {}
    agent_state["web_searched_info"] = []
    if _uses_template(agent_state) or brief.get("research") is False:
        return agent_state
    if not agent_state.get("company_name") or not os.environ.get("search_api_key"):
        return agent_state

    from utils.WebSearchAgent import WebSearchAgent

    query = agent_state["company_name"]
    if agent_state.get("details"):
        query = f"{query} {agent_state['details']}"
    try:
        agent_state["web_searched_info"] = WebSearchAgent(query=query).search_agent()
    except Exception as exc:  # research is best-effort; the writer still has the row details
        print(f"Web search skipped for {agent_state['company_name']}: {exc}", flush=True)
    return agent_state


def summarizer(agent_state: AgentState) -> AgentState:
    fallback = agent_state.get("details", "")
    if agent_state.get("company_name"):
        fallback = f"{agent_state['company_name']}. {fallback}".strip()
    agent_state["summarised_company_info"] = fallback
    if not agent_state.get("web_searched_info"):
        return agent_state

    from utils.SummariserAgent import Summarizer

    try:
        summary = Summarizer().summarize(company_info=agent_state["web_searched_info"])
        agent_state["summarised_company_info"] = f"{summary}\nAdditional notes: {agent_state.get('details', '')}".strip()
    except Exception as exc:
        print(f"Summary skipped for {agent_state.get('company_name')}: {exc}", flush=True)
    return agent_state


def project_selector(agent_state: AgentState) -> AgentState:
    if agent_state.get("projects") or agent_state.get("role") == "campaigner" or _uses_template(agent_state):
        return agent_state

    catalog = agent_state.get("project_catalog") or {}
    if len(catalog) <= 3:
        agent_state["projects"] = list(catalog)
        return agent_state

    from utils.ProjectSelector import ProjectSelector

    try:
        selected = ProjectSelector(catalog).select_projects(agent_state.get("summarised_company_info", ""))
    except Exception as exc:
        print(f"Project selection fell back to the first projects: {exc}", flush=True)
        selected = []
    agent_state["projects"] = [name for name in selected if name in catalog] or list(catalog)[:3]
    return agent_state


def email_writer(agent_state: AgentState) -> AgentState:
    if _uses_template(agent_state):
        from utils.job_templates import profile_variables
        from utils.templating import render_template

        brief = agent_state.get("brief") or {}
        context = " ".join(filter(None, [agent_state.get("company_name"), agent_state.get("details")]))
        # Contact columns win over profile-derived fields with the same name.
        variables = {
            **profile_variables(agent_state.get("profile") or {}, agent_state.get("project_catalog") or {}, context),
            **(agent_state.get("variables") or {}),
        }
        drop = bool(brief.get("drop_empty_lines"))
        agent_state["written_email_details"] = EmailDetails(
            email_subject=render_template(brief.get("subject_template", ""), variables, drop_empty_lines=drop),
            email_body=render_template(brief.get("body_template", ""), variables, html=True, drop_empty_lines=drop),
        )
        if variables.get("project_name") and not agent_state.get("projects"):
            agent_state["projects"] = [variables["project_name"]]
        return agent_state

    from utils.EmailWriter import EmailWriter

    writer = EmailWriter()
    if agent_state.get("role") == "campaigner":
        agent_state["written_email_details"] = writer.WriteCampaignEmail(
            brief=agent_state.get("brief") or {},
            profile=agent_state.get("profile") or {},
            company_info=agent_state.get("summarised_company_info", ""),
            recipient_name=agent_state.get("recipient_name", ""),
            recipient_email=agent_state["recipient_email"],
        )
        return agent_state

    catalog = agent_state.get("project_catalog") or {}
    selected = agent_state.get("projects", [])
    project_content = {name: catalog.get(name, "") for name in selected} if catalog else selected
    agent_state["written_email_details"] = writer.WriteEmail(
        project_content=project_content,
        company_info=agent_state.get("summarised_company_info", ""),
        recipient_name=agent_state.get("recipient_name", ""),
        recipient_email=agent_state["recipient_email"],
        profile=agent_state.get("profile") or {},
        brief=agent_state.get("brief") or {},
    )
    return agent_state


def compliance_footer(agent_state: AgentState) -> AgentState:
    if agent_state.get("role") != "campaigner":
        return agent_state
    from utils.templating import with_compliance_footer

    details = agent_state["written_email_details"]
    agent_state["written_email_details"] = EmailDetails(
        email_subject=details.email_subject,
        email_body=with_compliance_footer(details.email_body, agent_state.get("profile") or {}),
    )
    return agent_state


def pre_send_risk_analyzer(agent_state: AgentState) -> AgentState:
    from utils.spam_guard import analyze_email_risk

    campaign_type = campaign_type_for(agent_state)
    email_details = agent_state["written_email_details"]
    risk = analyze_email_risk(
        email_details.email_subject,
        email_details.email_body,
        agent_state["email_from"],
        agent_state["recipient_email"],
        campaign_type=campaign_type,
    )
    history = [risk.model_dump()]

    # Template campaigns are the user's own words, so a risky one goes to review instead of an AI rewrite.
    if risk.action == "REGENERATE" and not _uses_template(agent_state):
        from utils.EmailWriter import EmailWriter

        writer = EmailWriter()
        rewritten = writer.RewriteForDeliverability(
            email_details.email_subject,
            email_details.email_body,
            risk.reasons,
        )
        agent_state["written_email_details"] = rewritten
        compliance_footer(agent_state)
        rewritten = agent_state["written_email_details"]
        risk = analyze_email_risk(
            rewritten.email_subject,
            rewritten.email_body,
            agent_state["email_from"],
            agent_state["recipient_email"],
            campaign_type=campaign_type,
        )
        history.append(risk.model_dump())

    agent_state["deliverability_history"] = history
    agent_state["deliverability_risk"] = risk.model_dump()
    agent_state["outreach_status"] = risk.action
    return agent_state


def _save_kwargs(agent_state: AgentState) -> dict[str, Any]:
    return {
        "campaign_id": agent_state.get("campaign_id"),
        "campaign_name": agent_state.get("campaign_name"),
        "campaign_type": campaign_type_for(agent_state),
    }


def save_to_db(agent_state: AgentState) -> AgentState:
    from database.fxns import save_email

    agent_state["final_email_status"] = False
    agent_state["db_id"] = save_email(
        agent_state.get("projects", []),
        agent_state["written_email_details"],
        agent_state.get("company_name", ""),
        agent_state.get("recipient_name", ""),
        agent_state["recipient_email"],
        agent_state["email_from"],
        agent_state["final_email_status"],
        agent_state["user_id"],
        deliverability_risk=agent_state.get("deliverability_risk"),
        outreach_status=agent_state.get("outreach_status") or "REVIEW_REQUIRED",
        **_save_kwargs(agent_state),
    )
    return agent_state


def emailer_agent(agent_state: AgentState) -> AgentState:
    from database.fxns import record_generated_send_result, save_email
    from utils.GmailAuth import get_valid_gmail_tokens
    from utils.EmailerAgent import EmailerAgent

    risk = agent_state.get("deliverability_risk") or {}
    if risk.get("action") != "SEND":
        agent_state["final_email_status"] = False
        agent_state["db_id"] = save_email(
            agent_state.get("projects", []),
            agent_state["written_email_details"],
            agent_state.get("company_name", ""),
            agent_state.get("recipient_name", ""),
            agent_state["recipient_email"],
            agent_state["email_from"],
            agent_state["final_email_status"],
            agent_state["user_id"],
            deliverability_risk=risk,
            outreach_status=risk.get("action", "REVIEW_REQUIRED"),
            **_save_kwargs(agent_state),
        )
        return agent_state

    from utils.plans import QuotaExceeded, ensure_can_send

    try:
        ensure_can_send(agent_state["user_id"])
    except QuotaExceeded as exc:
        agent_state["final_email_status"] = False
        agent_state["quota_blocked"] = True
        agent_state["outreach_status"] = "QUOTA_REACHED"
        agent_state["db_id"] = save_email(
            agent_state.get("projects", []),
            agent_state["written_email_details"],
            agent_state.get("company_name", ""),
            agent_state.get("recipient_name", ""),
            agent_state["recipient_email"],
            agent_state["email_from"],
            False,
            agent_state["user_id"],
            deliverability_risk=risk,
            outreach_status="QUOTA_REACHED",
            failure_reason=str(exc),
            **_save_kwargs(agent_state),
        )
        return agent_state

    pending_id = save_email(
        agent_state.get("projects", []),
        agent_state["written_email_details"],
        agent_state.get("company_name", ""),
        agent_state.get("recipient_name", ""),
        agent_state["recipient_email"],
        agent_state["email_from"],
        False,
        agent_state["user_id"],
        deliverability_risk=risk,
        outreach_status="SENDING",
        **_save_kwargs(agent_state),
    )
    agent_state["db_id"] = pending_id

    try:
        gmail_tokens = get_valid_gmail_tokens(agent_state["user_id"])
    except HTTPException as exc:
        send_result = {
            "status": "FAILED_PERMANENT",
            "attempt": 0,
            "reason": exc.detail,
            "history": [{"attempt": 0, "status": "FAILED", "reason": exc.detail, "transient": False}],
        }
        persisted = record_generated_send_result(pending_id, agent_state["user_id"], send_result, risk)
        agent_state["email_response"] = send_result
        agent_state["final_email_status"] = False
        agent_state["outreach_status"] = persisted.get("outreach_status", "FAILED_PERMANENT")
        return agent_state

    emailer = EmailerAgent(
        email_details=agent_state["written_email_details"],
        recipient_email=agent_state["recipient_email"],
        email_from=agent_state["email_from"],
        gmail_tokens=gmail_tokens,
    )
    send_result = emailer.send_with_retries()
    agent_state["email_response"] = send_result
    agent_state["final_email_status"] = send_result.get("status") == "SENT"
    persisted = record_generated_send_result(pending_id, agent_state["user_id"], send_result, risk)
    agent_state["db_id"] = persisted["id"]
    agent_state["outreach_status"] = persisted.get("outreach_status", send_result.get("status", "FAILED"))
    return agent_state


def _base_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("WebSearchNode", web_search_agent)
    graph.add_node("SummarizerNode", summarizer)
    graph.add_node("ProjectSelectorNode", project_selector)
    graph.add_node("EmailWriterNode", email_writer)
    graph.add_node("ComplianceNode", compliance_footer)
    graph.add_node("PreSendRiskNode", pre_send_risk_analyzer)
    graph.add_edge(START, "WebSearchNode")
    graph.add_edge("WebSearchNode", "SummarizerNode")
    graph.add_edge("SummarizerNode", "ProjectSelectorNode")
    graph.add_edge("ProjectSelectorNode", "EmailWriterNode")
    graph.add_edge("EmailWriterNode", "ComplianceNode")
    graph.add_edge("ComplianceNode", "PreSendRiskNode")
    return graph


automated_graph = _base_graph()
automated_graph.add_node("EmailerNode", emailer_agent)
automated_graph.add_edge("PreSendRiskNode", "EmailerNode")
automated_graph.add_edge("EmailerNode", END)
automated_app = automated_graph.compile()

human_in_loop_graph = _base_graph()
human_in_loop_graph.add_node("DbSaverNode", save_to_db)
human_in_loop_graph.add_edge("PreSendRiskNode", "DbSaverNode")
human_in_loop_graph.add_edge("DbSaverNode", END)
human_in_loop_app = human_in_loop_graph.compile()


def run_outreach(input_data: OutreachInput, automate: bool) -> AgentState:
    state: AgentState = {
        "user_id": input_data.user_id,
        "role": input_data.role,
        "campaign_id": input_data.campaign_id,
        "campaign_name": input_data.campaign_name,
        "profile": input_data.profile,
        "brief": input_data.brief,
        "variables": input_data.variables,
        "project_catalog": input_data.project_catalog,
        "company_name": input_data.company_name,
        "recipient_name": input_data.recipient_name,
        "recipient_email": input_data.recipient_email,
        "email_from": input_data.email_from,
        "details": input_data.details,
        "projects": input_data.projects,
        "final_email_status": False,
    }
    app = automated_app if automate else human_in_loop_app
    return app.invoke(state)
