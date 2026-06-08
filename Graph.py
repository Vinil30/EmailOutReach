from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
load_dotenv()

class EmailDetails(BaseModel):
    email_subject: str
    email_body: str
    
class AgentState(BaseModel):
    projects: list[str] = Field(default_factory=list)
    web_searched_info: str = ""
    summarised_company_info: str = ""
    written_email_details: EmailDetails | None = None
    company_name: str = ""
    recipient_name: str = ""
    recipient_email: str = ""
    final_email_status : bool = False

def web_search_agent(agent_state: AgentState) -> AgentState:
    from utils.WebSearchAgent import WebSearchAgent
    WebAgent = WebSearchAgent(query=agent_state["company_name"])
    agent_state["web_searched_info"] = WebAgent.search_agent()
    return agent_state

def summarizer(agent_state:AgentState) -> AgentState:
    from utils.SummariserAgent import Summarizer
    summarizer = Summarizer()
    agent_state["summarised_company_info"] = summarizer.summarize(company_info=agent_state["web_searched_info"])
    return agent_state

def project_selector(agent_state:AgentState)->AgentState:
    from utils.ProjectSelector import ProjectSelector
    ps = ProjectSelector()
    agent_state["projects"] = ps.select_projects(agent_state["summarised_company_info"])
    return agent_state

def EmailWriter(agent_state:AgentState)->AgentState:
    from utils.EmailWriter import EmailWriter
    ew = EmailWriter()
    agent_state["written_email_details"] = ew.WriteEmail(project_content = agent_state["projects"],
                                                         company_info=agent_state["summarised_company_info"],
                                                          recipient_name = agent_state["recipient_name"],
                                                           recipient_email = agent_state["recipient_email"] )
    return agent_state


def save_to_db(agent_state:AgentState)->AgentState:
    pass

def emailer_agent(agent_state:AgentState)->AgentState:
    from utils.EmailerAgent import EmailerAgent
    ea = EmailerAgent(email_details=agent_state["written_email_details"], recipient_email = agent_state["recipient_email"])
    agent_state["final_email_status"] = True
    return agent_state


automated_graph = StateGraph(AgentState)
automated_graph.add_node("WebSearchNode",web_search_agent)
automated_graph.add_node("SummarizerNode",summarizer)
automated_graph.add_node("ProjectSelectorNode",project_selector)
automated_graph.add_node("EmailWriterNode",EmailWriter)
automated_graph.add_node("EmailerNode",emailer_agent)

automated_graph.add_edge(START, "WebSearchNode")
automated_graph.add_edge("WebSearchNode","SummarizerNode")
automated_graph.add_edge("SummarizerNode","ProjectSelectorNode")
automated_graph.add_edge("ProjectSelectorNode","EmailWriterNode")
automated_graph.add_edge("EmailWriterNode","EmailerNode")
automated_graph.add_edge("EmailerNode",END)

huamn_in_loop_graph = StateGraph(AgentState)
huamn_in_loop_graph.add_node("WebSearchNode",web_search_agent)
huamn_in_loop_graph.add_node("SummarizerNode",summarizer)
huamn_in_loop_graph.add_node("ProjectSelectorNode",project_selector)
huamn_in_loop_graph.add_node("EmailWriterNode",EmailWriter)
huamn_in_loop_graph.add_node("DbSaverNode",save_to_db)

huamn_in_loop_graph.add_edge(START, "WebSearchNode")
huamn_in_loop_graph.add_edge("WebSearchNode","SummarizerNode")
huamn_in_loop_graph.add_edge("SummarizerNode","ProjectSelectorNode")
huamn_in_loop_graph.add_edge("ProjectSelectorNode","EmailWriterNode")
huamn_in_loop_graph.add_edge("EmailWriterNode","DbSaverNode")
huamn_in_loop_graph.add_edge("DbSaverNode",END)


