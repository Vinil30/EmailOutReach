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


class OutreachInput(BaseModel):
    user_id: str
    company_name: str
    recipient_name: str
    recipient_email: str
    email_from: str
    details: str = ""
    projects: list[str] = Field(default_factory=list)


def web_search_agent(agent_state: AgentState) -> AgentState:
    from utils.WebSearchAgent import WebSearchAgent

    query = agent_state["company_name"]
    if agent_state.get("details"):
        query = f"{query} {agent_state['details']}"

    web_agent = WebSearchAgent(query=query)
    agent_state["web_searched_info"] = web_agent.search_agent()
    return agent_state


def summarizer(agent_state: AgentState) -> AgentState:
    from utils.SummariserAgent import Summarizer

    summarizer_agent = Summarizer()
    agent_state["summarised_company_info"] = summarizer_agent.summarize(
        company_info=agent_state.get("web_searched_info", [])
    )
    return agent_state


def project_selector(agent_state: AgentState) -> AgentState:
    from utils.ProjectSelector import ProjectSelector

    if agent_state.get("projects"):
        return agent_state

    selector = ProjectSelector()
    agent_state["projects"] = selector.select_projects(agent_state.get("summarised_company_info", ""))
    return agent_state


def email_writer(agent_state: AgentState) -> AgentState:
    from utils.EmailWriter import EmailWriter

    writer = EmailWriter()
    agent_state["written_email_details"] = writer.WriteEmail(
        project_content=agent_state.get("projects", []),
        company_info=agent_state.get("summarised_company_info", ""),
        recipient_name=agent_state["recipient_name"],
        recipient_email=agent_state["recipient_email"],
    )
    return agent_state


def pre_send_risk_analyzer(agent_state: AgentState) -> AgentState:
    from utils.DeliverabilityAnalyzer import RspamdAnalyzer
    from utils.EmailWriter import EmailWriter

    analyzer = RspamdAnalyzer()
    email_details = agent_state["written_email_details"]
    risk = analyzer.analyze(
        email_details.email_subject,
        email_details.email_body,
        agent_state["email_from"],
        agent_state["recipient_email"],
    )
    history = [risk.model_dump()]

    if risk.level == "MEDIUM":
        writer = EmailWriter()
        rewritten = writer.RewriteForDeliverability(
            email_details.email_subject,
            email_details.email_body,
            risk.reasons,
        )
        agent_state["written_email_details"] = rewritten
        risk = analyzer.analyze(
            rewritten.email_subject,
            rewritten.email_body,
            agent_state["email_from"],
            agent_state["recipient_email"],
        )
        history.append(risk.model_dump())

    agent_state["deliverability_history"] = history
    agent_state["deliverability_risk"] = risk.model_dump()
    agent_state["outreach_status"] = risk.action
    return agent_state


def save_to_db(agent_state: AgentState) -> AgentState:
    from database.fxns import save_email

    agent_state["final_email_status"] = False
    agent_state["db_id"] = save_email(
        agent_state.get("projects", []),
        agent_state["written_email_details"],
        agent_state["company_name"],
        agent_state["recipient_name"],
        agent_state["recipient_email"],
        agent_state["email_from"],
        agent_state["final_email_status"],
        agent_state["user_id"],
        deliverability_risk=agent_state.get("deliverability_risk"),
        outreach_status=agent_state.get("outreach_status") or "REVIEW_REQUIRED",
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
            agent_state["company_name"],
            agent_state["recipient_name"],
            agent_state["recipient_email"],
            agent_state["email_from"],
            agent_state["final_email_status"],
            agent_state["user_id"],
            deliverability_risk=risk,
            outreach_status=risk.get("action", "REVIEW_REQUIRED"),
        )
        return agent_state

    pending_id = save_email(
        agent_state.get("projects", []),
        agent_state["written_email_details"],
        agent_state["company_name"],
        agent_state["recipient_name"],
        agent_state["recipient_email"],
        agent_state["email_from"],
        False,
        agent_state["user_id"],
        deliverability_risk=risk,
        outreach_status="SENDING",
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
    graph.add_node("PreSendRiskNode", pre_send_risk_analyzer)
    graph.add_edge(START, "WebSearchNode")
    graph.add_edge("WebSearchNode", "SummarizerNode")
    graph.add_edge("SummarizerNode", "ProjectSelectorNode")
    graph.add_edge("ProjectSelectorNode", "EmailWriterNode")
    graph.add_edge("EmailWriterNode", "PreSendRiskNode")
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
