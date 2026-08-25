import streamlit as st
from dotenv import load_dotenv
load_dotenv()

from agent_app.graph.graph import graph
from langgraph.types import Command
from run_demo import SAMPLE_EMAILS

st.set_page_config(page_title="Dropshipping Email Agent", page_icon="📧")
st.title("Dropshipping Email Agent")
st.caption("LangGraph agent — live demo, running on mock data (no API keys needed).")

if "pending" not in st.session_state:
    st.session_state.pending = None

mode = st.radio("Email source:", ["Sample email", "Write your own"], horizontal=True)

if mode == "Sample email":
    labels = [f"{e['email_id']} — {e['subject']}" for e in SAMPLE_EMAILS]
    choice = st.selectbox("Pick a sample email to run through the agent:", labels)
    email = dict(SAMPLE_EMAILS[labels.index(choice)])
    st.text_area("Email body", email["body"], height=100, disabled=True)
else:
    st.caption("Runs the exact same graph — just with whatever you type below.")
    inbox_source = st.selectbox(
        "Inbox it arrived at",
        ["support@company.com", "orders@company.com", "info@company.com"],
    )
    sender = st.text_input("Sender email", "customer@example.com")
    subject = st.text_input("Subject", "")
    body = st.text_area("Body", "", height=140)
    email = {
        "email_id": f"custom-{abs(hash((sender, subject, body))) % 100000}",
        "inbox_source": inbox_source,
        "sender": sender,
        "subject": subject,
        "body": body,
        "attachments": [],
    }

run_disabled = mode == "Write your own" and not email["body"].strip()

if st.button("▶ Run through agent", type="primary", disabled=run_disabled):
    config = {"configurable": {"thread_id": email["email_id"]}}
    result = graph.invoke(email, config)

    if "__interrupt__" in result:
        st.session_state.pending = (email["email_id"], result["__interrupt__"][0].value)
    else:
        st.session_state.pending = None
        st.success(f"Decision: **{result.get('decision')}**  |  Status: **{result.get('final_status')}**")
        st.json({k: v for k, v in result.items() if k not in ("email_id",) and v not in (None, "", False)})

if st.session_state.pending:
    thread_id, interrupt_info = st.session_state.pending
    st.warning("⏸ Paused — escalated for human input")
    st.write(interrupt_info)
    reply = st.text_input("Simulated human response:", "Approved manually - go ahead and process a full refund.")
    if st.button("Resume with this response"):
        config = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(Command(resume=reply), config)
        st.session_state.pending = None
        st.success(f"Resumed — Decision: **{result.get('decision')}**  |  Status: **{result.get('final_status')}**")
        st.json({k: v for k, v in result.items() if v not in (None, "", False)})
