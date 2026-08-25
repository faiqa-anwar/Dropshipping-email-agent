import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import os
st.write("Key detected:", bool(os.environ.get("OPENROUTER_API_KEY")))
st.write("Key prefix:", os.environ.get("OPENROUTER_API_KEY", "")[:8])
from agent_app.graph.graph import graph
from langgraph.types import Command
from run_demo import SAMPLE_EMAILS

st.set_page_config(page_title="Dropshipping Email Agent", page_icon="📧")
st.title("📧 Dropshipping Email Agent")
st.caption("LangGraph agent — live demo, running on mock data (no API keys needed).")

labels = [f"{e['email_id']} — {e['subject']}" for e in SAMPLE_EMAILS]
choice = st.selectbox("Pick a sample email to run through the agent:", labels)
email = SAMPLE_EMAILS[labels.index(choice)]

st.text_area("Email body", email["body"], height=100, disabled=True)

if "pending" not in st.session_state:
    st.session_state.pending = None

if st.button("▶ Run through agent", type="primary"):
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
    if st.button("✅ Resume with this response"):
        config = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(Command(resume=reply), config)
        st.session_state.pending = None
        st.success(f"Resumed — Decision: **{result.get('decision')}**  |  Status: **{result.get('final_status')}**")
        st.json({k: v for k, v in result.items() if v not in (None, "", False)})
