"""MeetTrack Streamlit application.

Polished, modern, interactive FYP action-tracking dashboard with a purple-and-white
visual identity, robust light and dark themes, interactive 8-step tutorial guide,
repositioned floating MeetTrack mascot ("Tracky"), comprehensive team management,
meeting-note processing with Ollama, human-approval proposal review, versioned action
register, auditable Excel exports, and UNSENT reminder drafts.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import streamlit as st

from api_client import ApiClient, ApiError

# ---------------------------------------------------------------------------
# 1. Page Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="MeetTrack | Agentic Action Tracker",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# 2. Session State Initialization
# ---------------------------------------------------------------------------
if "api_client" not in st.session_state:
    st.session_state.api_client = ApiClient()

client: ApiClient = st.session_state.api_client

if "theme" not in st.session_state:
    st.session_state.theme = "light"
if "current_page" not in st.session_state:
    st.session_state.current_page = "Dashboard"
if "selected_team_id" not in st.session_state:
    st.session_state.selected_team_id = None
if "selected_team_name" not in st.session_state:
    st.session_state.selected_team_name = None
if "active_cycle_id" not in st.session_state:
    st.session_state.active_cycle_id = None
if "last_report" not in st.session_state:
    st.session_state.last_report = None
if "team_to_delete" not in st.session_state:
    st.session_state.team_to_delete = None
if "show_tutorial" not in st.session_state:
    st.session_state.show_tutorial = False
if "tutorial_step" not in st.session_state:
    st.session_state.tutorial_step = 1

# Check query param trigger for tutorial
if st.query_params.get("tutorial") == "true":
    st.session_state.show_tutorial = True
    st.query_params.clear()


# ---------------------------------------------------------------------------
# 3. Global CSS Theme Engine (Light & Dark with Purple Identity)
# ---------------------------------------------------------------------------
def inject_custom_styles(theme: str) -> None:
    is_dark = theme == "dark"

    # Theme Variable Definitions
    if is_dark:
        bg_app = "#13111C"
        bg_card = "#1F1B2E"
        bg_card_sub = "#27223A"
        bg_input = "#1A1726"
        text_primary = "#F8FAFC"
        text_secondary = "#CBD5E1"
        text_muted = "#94A3B8"
        border_color = "#38314F"
        border_hover = "#7C3AED"
        shadow_sm = "0 2px 8px rgba(0, 0, 0, 0.4)"
        shadow_lg = "0 8px 24px rgba(0, 0, 0, 0.55)"
        code_bg = "#2B2444"
        code_text = "#C4B5FD"
        popover_bg = "#1F1B2E"
        badge_purple_bg = "#382A61"
        badge_purple_text = "#DDD6FE"
        badge_green_bg = "#163826"
        badge_green_text = "#86EFAC"
        badge_amber_bg = "#3F2F14"
        badge_amber_text = "#FDE047"
        badge_blue_bg = "#1D2C5A"
        badge_blue_text = "#93C5FD"
        badge_red_bg = "#3E1B1B"
        badge_red_text = "#FCA5A5"
    else:
        bg_app = "#F8F7FD"
        bg_card = "#FFFFFF"
        bg_card_sub = "#F4F0FF"
        bg_input = "#FFFFFF"
        text_primary = "#1E1B4B"
        text_secondary = "#475569"
        text_muted = "#64748B"
        border_color = "#E2E8F0"
        border_hover = "#7C3AED"
        shadow_sm = "0 2px 10px rgba(124, 58, 237, 0.05)"
        shadow_lg = "0 8px 24px rgba(124, 58, 237, 0.1)"
        code_bg = "#EDE9FE"
        code_text = "#5B21B6"
        popover_bg = "#FFFFFF"
        badge_purple_bg = "#EDE9FE"
        badge_purple_text = "#5B21B6"
        badge_green_bg = "#DCFCE7"
        badge_green_text = "#15803D"
        badge_amber_bg = "#FEF3C7"
        badge_amber_text = "#B45309"
        badge_blue_bg = "#DBEAFE"
        badge_blue_text = "#1D4ED8"
        badge_red_bg = "#FEE2E2"
        badge_red_text = "#B91C1C"

    css = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }}

    .stApp {{
        background-color: {bg_app} !important;
        color: {text_primary} !important;
    }}

    header[data-testid="stHeader"] {{
        background: transparent !important;
    }}

    .block-container {{
        padding-top: 1.2rem !important;
        padding-bottom: 5rem !important;
        max-width: 1260px;
    }}

    /* Card System */
    .mt-card {{
        background-color: {bg_card};
        border: 1px solid {border_color};
        border-radius: 16px;
        padding: 1.35rem;
        box-shadow: {shadow_sm};
        margin-bottom: 1.1rem;
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
    }}

    .mt-card:hover {{
        box-shadow: {shadow_lg};
        border-color: {border_hover};
    }}

    .mt-card-title {{
        font-size: 1.15rem;
        font-weight: 700;
        color: {text_primary};
        margin-bottom: 0.35rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }}

    .mt-card-subtitle {{
        font-size: 0.88rem;
        color: {text_secondary};
        margin-bottom: 0.9rem;
    }}

    /* Metric Card */
    .mt-metric {{
        background: {bg_card};
        border: 1px solid {border_color};
        border-radius: 16px;
        padding: 1.15rem;
        box-shadow: {shadow_sm};
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 105px;
        border-top: 4px solid #7C3AED;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }}

    .mt-metric:hover {{
        transform: translateY(-2px);
        box-shadow: {shadow_lg};
    }}

    .mt-metric-val {{
        font-size: 2rem;
        font-weight: 800;
        color: #7C3AED;
        line-height: 1.1;
    }}

    .mt-metric-lbl {{
        font-size: 0.82rem;
        font-weight: 700;
        color: {text_secondary};
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}

    .mt-metric-desc {{
        font-size: 0.78rem;
        color: {text_muted};
        margin-top: 0.25rem;
    }}

    /* Badges & Chips */
    .mt-badge {{
        display: inline-block;
        padding: 0.22rem 0.65rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }}

    .badge-purple {{ background-color: {badge_purple_bg}; color: {badge_purple_text}; }}
    .badge-green {{ background-color: {badge_green_bg}; color: {badge_green_text}; }}
    .badge-amber {{ background-color: {badge_amber_bg}; color: {badge_amber_text}; }}
    .badge-blue {{ background-color: {badge_blue_bg}; color: {badge_blue_text}; }}
    .badge-red {{ background-color: {badge_red_bg}; color: {badge_red_text}; }}

    .code-pill {{
        background-color: {code_bg};
        color: {code_text};
        padding: 0.2rem 0.55rem;
        border-radius: 6px;
        font-family: monospace;
        font-size: 0.82rem;
        font-weight: 600;
    }}

    /* Streamlit Native Input Styling Overrides */
    div[data-testid="stTextInput"] input,
    div[data-testid="stTextArea"] textarea,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
        background-color: {bg_input} !important;
        color: {text_primary} !important;
        border-color: {border_color} !important;
        border-radius: 10px !important;
    }}

    div[data-testid="stTextInput"] input:focus,
    div[data-testid="stTextArea"] textarea:focus {{
        border-color: #7C3AED !important;
        box-shadow: 0 0 0 1px #7C3AED !important;
    }}

    div[data-testid="stDateInput"] input {{
        background-color: {bg_input} !important;
        color: {text_primary} !important;
        border-radius: 10px !important;
    }}

    /* Streamlit Popover styling */
    div[data-testid="stPopoverBody"] {{
        background-color: {popover_bg} !important;
        border: 1px solid {border_color} !important;
        border-radius: 14px !important;
        box-shadow: {shadow_lg} !important;
        color: {text_primary} !important;
    }}

    /* Primary and Secondary Buttons */
    button[kind="primary"] {{
        background: linear-gradient(135deg, #7C3AED 0%, #5B21B6 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        padding: 0.5rem 1.25rem !important;
        box-shadow: 0 4px 14px rgba(124, 58, 237, 0.3) !important;
        transition: all 0.18s ease !important;
    }}

    button[kind="primary"]:hover {{
        box-shadow: 0 6px 20px rgba(124, 58, 237, 0.45) !important;
        transform: translateY(-1px) !important;
    }}

    button[kind="secondary"] {{
        border-radius: 10px !important;
        border: 1px solid {border_color} !important;
        color: {text_primary} !important;
        background-color: {bg_card} !important;
        font-weight: 600 !important;
        transition: all 0.15s ease !important;
    }}

    button[kind="secondary"]:hover {{
        border-color: #7C3AED !important;
        color: #7C3AED !important;
    }}

    /* Streamlit Expander styling */
    .streamlit-expanderHeader {{
        background-color: {bg_card} !important;
        border-radius: 10px !important;
        color: {text_primary} !important;
        font-weight: 600 !important;
        border: 1px solid {border_color} !important;
    }}

    /* Floating Mascot in Bottom-Right Viewport */
    .mt-floating-mascot-box {{
        position: fixed;
        bottom: 22px;
        right: 28px;
        z-index: 9999;
        display: flex;
        align-items: flex-end;
        gap: 10px;
        text-decoration: none;
        pointer-events: auto;
    }}

    .mt-mascot-bubble {{
        background: {bg_card};
        border: 1px solid {border_color};
        color: {text_primary};
        border-radius: 14px;
        padding: 8px 14px;
        box-shadow: {shadow_lg};
        font-size: 0.82rem;
        max-width: 250px;
        line-height: 1.35;
        border-left: 3px solid #7C3AED;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}

    .mt-mascot-bubble:hover {{
        transform: scale(1.02);
        box-shadow: 0 8px 26px rgba(124, 58, 237, 0.25);
    }}

    .mt-mascot-avatar-btn {{
        background: {bg_card};
        border: 2px solid #7C3AED;
        border-radius: 50%;
        width: 60px;
        height: 60px;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 6px 20px rgba(124, 58, 237, 0.35);
        cursor: pointer;
        transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
        animation: bob 3.5s ease-in-out infinite;
    }}

    .mt-mascot-avatar-btn:hover {{
        transform: scale(1.15) translateY(-4px);
    }}

    @keyframes bob {{
        0% {{ transform: translateY(0px); }}
        50% {{ transform: translateY(-7px); }}
        100% {{ transform: translateY(0px); }}
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


inject_custom_styles(st.session_state.theme)


# ---------------------------------------------------------------------------
# 4. Helper: Fetch Teams Safely
# ---------------------------------------------------------------------------
def get_teams_list() -> list[dict[str, Any]]:
    try:
        return client.list_teams()
    except Exception:
        return []


teams_list = get_teams_list()

# Auto-select the first team if none is selected
if not st.session_state.selected_team_id and teams_list:
    st.session_state.selected_team_id = teams_list[0]["team_id"]
    st.session_state.selected_team_name = teams_list[0]["name"]
elif st.session_state.selected_team_id:
    matched = next((t for t in teams_list if t["team_id"] == st.session_state.selected_team_id), None)
    if matched:
        st.session_state.selected_team_name = matched["name"]
    elif teams_list:
        st.session_state.selected_team_id = teams_list[0]["team_id"]
        st.session_state.selected_team_name = teams_list[0]["name"]
    else:
        st.session_state.selected_team_id = None
        st.session_state.selected_team_name = None


# ---------------------------------------------------------------------------
# 5. Mascot SVG Illustration (Reusable & Compact)
# ---------------------------------------------------------------------------
def render_mascot_svg(size: int = 56) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="50" y1="20" x2="50" y2="8" stroke="#7C3AED" stroke-width="4" stroke-linecap="round"/>'
        f'<circle cx="50" cy="8" r="5" fill="#A78BFA"/>'
        f'<rect x="18" y="20" width="64" height="60" rx="20" fill="url(#paint0_linear)" stroke="#5B21B6" stroke-width="3"/>'
        f'<rect x="26" y="28" width="48" height="34" rx="12" fill="#171522"/>'
        f'<ellipse cx="38" cy="45" rx="4" ry="5.5" fill="#34D399"/>'
        f'<circle cx="40" cy="43" r="1.5" fill="white"/>'
        f'<ellipse cx="62" cy="45" rx="4" ry="5.5" fill="#34D399"/>'
        f'<circle cx="64" cy="43" r="1.5" fill="white"/>'
        f'<circle cx="32" cy="52" r="2.5" fill="#F472B6" opacity="0.6"/>'
        f'<circle cx="68" cy="52" r="2.5" fill="#F472B6" opacity="0.6"/>'
        f'<path d="M46 51 Q50 54 54 51" stroke="#34D399" stroke-width="2" stroke-linecap="round"/>'
        f'<rect x="32" y="80" width="10" height="7" rx="3" fill="#7C3AED"/>'
        f'<rect x="58" y="80" width="10" height="7" rx="3" fill="#7C3AED"/>'
        f'<rect x="42" y="66" width="16" height="10" rx="3" fill="#EDE9FE"/>'
        f'<path d="M46 71 L49 73 L54 68" stroke="#7C3AED" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<defs><linearGradient id="paint0_linear" x1="18" y1="20" x2="82" y2="80" gradientUnits="userSpaceOnUse">'
        f'<stop stop-color="#FFFFFF"/><stop offset="1" stop-color="#EDE9FE"/>'
        f'</linearGradient></defs></svg>'
    )


# ---------------------------------------------------------------------------
# 6. Interactive 8-Step Tutorial Modal
# ---------------------------------------------------------------------------
TUTORIAL_STEPS = [
    {
        "title": "Welcome to MeetTrack",
        "badge": "Agentic FYP Action Tracker",
        "description": (
            "MeetTrack helps students and project supervisors turn unstructured meeting notes into "
            "clear, tracked action items, deadlines, and auditable decisions.\n\n"
            "**Key Principles:**\n"
            "- **Zero Hallucination Risk:** Every action proposal is linked to an exact line quote.\n"
            "- **Human-in-the-Loop Gate:** The AI *never* updates persistent memory without supervisor approval.\n"
            "- **Immutable Versioning:** Every edit or status change creates a new auditable version in SQLite."
        ),
        "tip": "Everything begins by selecting or creating a team context.",
    },
    {
        "title": "Set Up Your Team",
        "badge": "Team Isolation",
        "description": (
            "Each team has complete isolation for its meetings, proposals, committed actions, and history.\n\n"
            "**How to Manage Teams:**\n"
            "1. Navigate to the **Teams** page.\n"
            "2. Enter your group name, supervisor, and student member names.\n"
            "3. Click **Create Team** — MeetTrack automatically sets it as your active team.\n"
            "4. When a team is finished or deleted, all associated data is safely removed in a single cascade."
        ),
        "tip": "Members registered here are used by Ollama to validate who owns which task.",
    },
    {
        "title": "Upload Meeting Notes",
        "badge": "Numbered Notes Format",
        "description": (
            "In the **Meeting Notes** page, upload your notes as a `.txt` file or paste them directly.\n\n"
            "**Expected Format:**\n"
            "Numbered plain-text lines with speaker attributions:\n"
            "```text\n"
            "Meeting 1 | 2026-10-05\n"
            "1. Bilal: I will collect 500 leaf images by Friday.\n"
            "2. Amna: I will label the dataset by Monday.\n"
            "```\n\n"
            "Select the meeting date and choose whether **Memory** is enabled (Persistent vs Dry Run)."
        ),
        "tip": "Clear speaker names make task ownership extraction 100% accurate.",
    },
    {
        "title": "Process Notes with Local Ollama",
        "badge": "AI Action Extraction",
        "description": (
            "Click **🚀 Process Notes with Local Ollama** to analyze your notes.\n\n"
            "**What Happens Next:**\n"
            "- MeetTrack connects to local Ollama running `qwen2.5:1.5b` (no API keys required).\n"
            "- It extracts commitments, maps them to team members, computes ISO deadlines, and captures exact evidence quotes.\n"
            "- Cross-references existing open actions to detect status updates or duplicate items.\n"
            "- On CPU, processing takes 30–60 seconds. A progress spinner keeps you informed."
        ),
        "tip": "Ensure Ollama is running (`ollama list`) before starting processing.",
    },
    {
        "title": "Review Proposals (Approval Gate)",
        "badge": "Human Approval Gate",
        "description": (
            "Extracted actions are stored as **pending proposals** awaiting human review.\n\n"
            "**Your Review Actions:**\n"
            "- **✅ Approve:** Accepts the proposal as extracted by the agent.\n"
            "- **✏️ Edit & Approve:** Modify description, owner, or due date before accepting.\n"
            "- **❌ Reject:** Drops the proposal with an optional comment (never committed).\n\n"
            "Once reviewed, click **🚀 Commit Approved Decisions to Memory** to update persistent storage."
        ),
        "tip": "Unapproved proposals NEVER modify persistent state.",
    },
    {
        "title": "Track Your Action Register",
        "badge": "Versioned Memory",
        "description": (
            "In the **Action Register** page, view all active and completed commitments.\n\n"
            "**Key Capabilities:**\n"
            "- **Status Tracking:** Instantly scan `open`, `done`, or `blocked` tasks.\n"
            "- **Overdue Detection:** Automatically flags tasks whose deadlines have passed.\n"
            "- **Action History:** Inspect any task to view its complete version history (v1, v2) and who changed it.\n"
            "- **Manual Corrections:** Directly correct an owner or date with an audited comment."
        ),
        "tip": "No record is ever overwritten — past versions are preserved as superseded.",
    },
    {
        "title": "Export and Prepare Reminders",
        "badge": "Exports & Drafts",
        "description": (
            "Generate formal exports and prepare follow-ups in the **Exports & Reminders** page.\n\n"
            "**What You Get:**\n"
            "- **Excel Action Register:** Two-sheet `.xlsx` file with current status and full history.\n"
            "- **UNSENT Reminder Drafts:** Automatically drafts personalized reminder messages for members with upcoming or overdue tasks.\n\n"
            "**Strict Privacy Rule:** Reminders are *never* sent automatically. They remain drafts for review only."
        ),
        "tip": "Copy draft texts into WhatsApp, Slack, or email as needed.",
    },
    {
        "title": "You're Ready to Roll!",
        "badge": "Quick Recap",
        "description": (
            "You now know the complete MeetTrack workflow:\n\n"
            "```text\n"
            "1. Select Team ➔ 2. Upload Notes ➔ 3. Ollama Process ➔ 4. Review & Commit ➔ 5. Track & Export\n"
            "```\n\n"
            "Need help anytime? Click the **🎓 Guide Me** button in the header or click **Tracky** in the bottom-right corner!"
        ),
        "tip": "Click 'Finish Tutorial' below to return to your dashboard.",
    },
]


def render_tutorial_dialog() -> None:
    step_idx = st.session_state.tutorial_step - 1
    step_data = TUTORIAL_STEPS[step_idx]

    st.markdown(
        f'<div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(124, 58, 237, 0.2); padding-bottom: 0.75rem; margin-bottom: 1rem;">'
        f'<div><span class="mt-badge badge-purple">{step_data["badge"]}</span>'
        f'<h3 style="margin: 0.35rem 0 0 0; color: #7C3AED; font-weight: 800;">{step_data["title"]}</h3></div>'
        f'<div style="text-align: right;"><span style="font-weight: 700; font-size: 0.88rem; color: #94A3B8;">Step {st.session_state.tutorial_step} of {len(TUTORIAL_STEPS)}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Progress bar
    st.progress(st.session_state.tutorial_step / len(TUTORIAL_STEPS))

    col_t_mascot, col_t_content = st.columns([1, 3.2])
    with col_t_mascot:
        svg_code = render_mascot_svg(size=85)
        st.markdown(
            f'<div style="text-align: center; padding: 0.5rem 0;">'
            f'<div class="mt-mascot-img">{svg_code}</div>'
            f'<div style="font-size: 0.85rem; font-weight: 700; color: #7C3AED; margin-top: 0.5rem;">Tracky</div>'
            f'<div style="font-size: 0.72rem; color: #94A3B8;">Your AI Guide</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with col_t_content:
        st.markdown(step_data["description"])
        st.info(f"💡 **Pro Tip:** {step_data['tip']}")

    st.markdown("<div style='height: 1.2rem;'></div>", unsafe_allow_html=True)

    # Navigation buttons
    c_prev, c_skip, c_next = st.columns([1.2, 1.5, 1.5])
    with c_prev:
        if st.session_state.tutorial_step > 1:
            if st.button("⬅️ Previous", key="tut_prev_btn"):
                st.session_state.tutorial_step -= 1
                st.rerun()

    with c_skip:
        if st.button("Skip Tutorial", key="tut_skip_btn"):
            st.session_state.show_tutorial = False
            st.session_state.tutorial_step = 1
            st.rerun()

    with c_next:
        if st.session_state.tutorial_step < len(TUTORIAL_STEPS):
            if st.button("Next ➡️", key="tut_next_btn", type="primary"):
                st.session_state.tutorial_step += 1
                st.rerun()
        else:
            if st.button("🎉 Finish Tutorial", key="tut_finish_btn", type="primary"):
                st.session_state.show_tutorial = False
                st.session_state.tutorial_step = 1
                st.rerun()


# Render tutorial dialog if active
if st.session_state.show_tutorial:
    if hasattr(st, "dialog"):
        @st.dialog("MeetTrack Interactive Guide", width="large")
        def _show_dialog() -> None:
            render_tutorial_dialog()

        _show_dialog()
    else:
        # Fallback card
        with st.container():
            st.markdown("<div class='mt-card' style='border: 2px solid #7C3AED;'>", unsafe_allow_html=True)
            render_tutorial_dialog()
            st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 7. TOP HEADER BAR
# ---------------------------------------------------------------------------
col_logo, col_team, col_status, col_guide, col_theme = st.columns([3.0, 3.2, 1.8, 1.4, 0.8])

with col_logo:
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 0.65rem;">
            <div style="background: linear-gradient(135deg, #7C3AED, #5B21B6); width: 38px; height: 38px; border-radius: 11px; display: flex; align-items: center; justify-content: center; color: white; font-size: 1.3rem; font-weight: 800; box-shadow: 0 4px 12px rgba(124, 58, 237, 0.35);">
                M
            </div>
            <div>
                <span style="font-size: 1.28rem; font-weight: 800; letter-spacing: -0.02em; color: #7C3AED;">MeetTrack</span>
                <span style="font-size: 0.72rem; display: block; color: #94A3B8; font-weight: 600; margin-top: -2px;">AI Action Tracker & Memory</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col_team:
    if teams_list:
        team_dict = {t["team_id"]: f"{t['name']}" for t in teams_list}
        selected_id = st.selectbox(
            "Active Team",
            options=list(team_dict.keys()),
            format_func=lambda tid: f"👥 {team_dict.get(tid, tid)}",
            index=list(team_dict.keys()).index(st.session_state.selected_team_id)
            if st.session_state.selected_team_id in team_dict
            else 0,
            label_visibility="collapsed",
            key="header_team_select",
        )
        if selected_id != st.session_state.selected_team_id:
            st.session_state.selected_team_id = selected_id
            st.session_state.selected_team_name = team_dict[selected_id]
            st.session_state.active_cycle_id = None
            st.rerun()
    else:
        st.caption("No teams registered yet")

with col_status:
    health = client.health()
    if health and health.get("status") == "ok":
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 0.45rem; padding-top: 6px;">
                <span style="width: 8px; height: 8px; border-radius: 50%; background-color: #10B981; display: inline-block;"></span>
                <span style="font-size: 0.78rem; font-weight: 700; color: #10B981;">Backend Connected</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 0.45rem; padding-top: 6px;">
                <span style="width: 8px; height: 8px; border-radius: 50%; background-color: #EF4444; display: inline-block;"></span>
                <span style="font-size: 0.78rem; font-weight: 700; color: #EF4444;">Backend Offline</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

with col_guide:
    if st.button("🎓 Guide Me", key="header_guide_btn", help="Open interactive step-by-step tutorial"):
        st.session_state.show_tutorial = True
        st.session_state.tutorial_step = 1
        st.rerun()

with col_theme:
    curr_theme = st.session_state.theme
    theme_icon = "🌙" if curr_theme == "light" else "☀️"
    if st.button(f"{theme_icon}", key="theme_toggle_btn", help=f"Switch to {'Dark' if curr_theme == 'light' else 'Light'} mode"):
        st.session_state.theme = "dark" if curr_theme == "light" else "light"
        st.rerun()

st.markdown("<div style='height: 0.4rem;'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 8. PRIMARY NAVIGATION BAR
# ---------------------------------------------------------------------------
PAGES = [
    ("Dashboard", "📊 Dashboard"),
    ("Teams", "👥 Teams"),
    ("Meeting Notes", "📝 Meeting Notes"),
    ("Proposal Review", "⚖️ Proposal Review"),
    ("Action Register", "📋 Action Register"),
    ("Exports & Reminders", "📦 Exports & Reminders"),
]

nav_cols = st.columns(len(PAGES))
for idx, (page_key, page_label) in enumerate(PAGES):
    with nav_cols[idx]:
        is_active = st.session_state.current_page == page_key
        btn_type = "primary" if is_active else "secondary"
        if st.button(page_label, key=f"nav_{page_key}", type=btn_type, use_container_width=True):
            st.session_state.current_page = page_key
            st.rerun()

st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)


# ===========================================================================
# PAGE 1: DASHBOARD
# ===========================================================================
if st.session_state.current_page == "Dashboard":
    team_id = st.session_state.selected_team_id
    team_name = st.session_state.selected_team_name

    # Welcoming Hero Banner with Guidance
    st.markdown(
        f"""
        <div class="mt-card" style="background: linear-gradient(135deg, rgba(124, 58, 237, 0.09) 0%, rgba(91, 33, 182, 0.03) 100%); border-left: 5px solid #7C3AED;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
                <div>
                    <h2 style="margin: 0; font-size: 1.45rem; font-weight: 800; color: #7C3AED;">
                        Active Context: {team_name or 'No Team Selected'}
                    </h2>
                    <p style="margin: 0.35rem 0 0 0; font-size: 0.88rem; color: #64748B;">
                        Track upcoming deadlines, review agent proposals, and verify student commitments.
                    </p>
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    <a href="?tutorial=true" style="text-decoration: none;">
                        <span class="mt-badge badge-purple" style="cursor: pointer;">📖 View 8-Step Tour</span>
                    </a>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not team_id:
        st.warning("No active team found. Please go to the **Teams** page to create your first FYP group.")
    else:
        # Fetch current team state
        try:
            team_actions = client.list_actions(team_id=team_id, include_done=True)
        except Exception:
            team_actions = []

        try:
            team_meetings = client.list_meetings(team_id=team_id)
        except Exception:
            team_meetings = []

        # Calculate metrics from real data
        today_iso = date.today().isoformat()
        next_week_iso = (date.today() + timedelta(days=7)).isoformat()

        open_actions = [a for a in team_actions if a.get("status") != "done"]
        overdue_actions = [
            a
            for a in open_actions
            if a.get("due_date") and a.get("due_date") < today_iso
        ]
        upcoming_actions = [
            a
            for a in open_actions
            if a.get("due_date") and today_iso <= a.get("due_date") <= next_week_iso
        ]

        # Pending proposals in active cycle if any
        pending_props_count = 0
        if st.session_state.active_cycle_id:
            try:
                cycle_props = client.list_proposals(team_id=team_id, cycle_id=st.session_state.active_cycle_id)
                pending_props_count = len([p for p in cycle_props if p.get("status") == "pending"])
            except Exception:
                pending_props_count = 0

        # Metric Cards Row
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(
                f"""
                <div class="mt-metric">
                    <span class="mt-metric-lbl">Active Actions</span>
                    <span class="mt-metric-val">{len(open_actions)}</span>
                    <span class="mt-metric-desc">Open & in-progress tasks</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with m2:
            st.markdown(
                f"""
                <div class="mt-metric" style="border-top-color: {'#EF4444' if overdue_actions else '#10B981'};">
                    <span class="mt-metric-lbl">Overdue</span>
                    <span class="mt-metric-val" style="color: {'#EF4444' if overdue_actions else '#10B981'};">{len(overdue_actions)}</span>
                    <span class="mt-metric-desc">Past targeted due date</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with m3:
            st.markdown(
                f"""
                <div class="mt-metric" style="border-top-color: #F59E0B;">
                    <span class="mt-metric-lbl">Pending Review</span>
                    <span class="mt-metric-val" style="color: #F59E0B;">{pending_props_count}</span>
                    <span class="mt-metric-desc">Proposals awaiting approval</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with m4:
            st.markdown(
                f"""
                <div class="mt-metric" style="border-top-color: #3B82F6;">
                    <span class="mt-metric-lbl">Due Next 7 Days</span>
                    <span class="mt-metric-val" style="color: #3B82F6;">{len(upcoming_actions)}</span>
                    <span class="mt-metric-desc">Immediate deadlines</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)

        col_dash_left, col_dash_right = st.columns([1.1, 0.9])

        with col_dash_left:
            st.markdown(
                """
                <div class="mt-card">
                    <div class="mt-card-title">📅 Recent Meeting History</div>
                    <div class="mt-card-subtitle">Processed numbered notes stored in auditable database</div>
                """,
                unsafe_allow_html=True,
            )
            if team_meetings:
                for mtg in team_meetings[:5]:
                    f_name = mtg.get("file_name", "notes.txt")
                    m_date = mtg.get("meeting_date") or "Date unrecorded"
                    hash_prev = (mtg.get("file_hash") or "")[:12]
                    st.markdown(
                        f"""
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.65rem 0; border-bottom: 1px dashed rgba(124, 58, 237, 0.15);">
                            <div>
                                <span style="font-weight: 700; font-size: 0.92rem;">{f_name}</span>
                                <span style="display: block; font-size: 0.78rem; color: #94A3B8;">Meeting Date: {m_date}</span>
                            </div>
                            <span class="code-pill">SHA: {hash_prev}...</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No meetings processed for this team yet. Use the shortcut below to upload notes.")

            st.markdown("</div>", unsafe_allow_html=True)

            c_btn1, c_btn2 = st.columns([1.4, 1.2])
            with c_btn1:
                if st.button("➕ Process New Meeting Notes", type="primary", use_container_width=True):
                    st.session_state.current_page = "Meeting Notes"
                    st.rerun()
            with c_btn2:
                if pending_props_count > 0:
                    if st.button(f"⚖️ Review Proposals ({pending_props_count})", use_container_width=True):
                        st.session_state.current_page = "Proposal Review"
                        st.rerun()

        with col_dash_right:
            st.markdown(
                """
                <div class="mt-card">
                    <div class="mt-card-title">⏰ Urgent & Upcoming Tasks</div>
                    <div class="mt-card-subtitle">Open commitments requiring supervisor attention</div>
                """,
                unsafe_allow_html=True,
            )
            urgent = overdue_actions + upcoming_actions
            if urgent:
                for act in urgent[:5]:
                    is_overdue = act in overdue_actions
                    badge_class = "badge-red" if is_overdue else "badge-blue"
                    status_lbl = "OVERDUE" if is_overdue else f"DUE {act.get('due_date')}"
                    desc = act.get("description", "")
                    owner = act.get("owner") or "Unassigned"
                    st.markdown(
                        f"""
                        <div style="padding: 0.65rem 0; border-bottom: 1px dashed rgba(124, 58, 237, 0.15);">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem;">
                                <span style="font-weight: 600; font-size: 0.88rem;">{desc}</span>
                                <span class="mt-badge {badge_class}">{status_lbl}</span>
                            </div>
                            <div style="font-size: 0.78rem; color: #94A3B8; margin-top: 0.2rem;">
                                👤 <strong>{owner}</strong> &bull; Code: <span class="code-pill">{act.get('action_code')}</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                if st.button("📋 View Full Action Register", use_container_width=True):
                    st.session_state.current_page = "Action Register"
                    st.rerun()
            elif open_actions:
                st.success("All actions are on track and no immediate deadlines are missed!")
            else:
                st.info("No active commitments recorded. Process meeting notes to start tracking.")

            st.markdown("</div>", unsafe_allow_html=True)


# ===========================================================================
# PAGE 2: TEAMS
# ===========================================================================
elif st.session_state.current_page == "Teams":
    st.markdown(
        """
        <div class="mt-card">
            <div class="mt-card-title">👥 Team Management</div>
            <div class="mt-card-subtitle">
                Each team maintains isolated meetings, committed actions, version history, and reminder drafts.
                Ensure student members are correctly registered for action ownership mapping.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Deletion Confirmation Banner
    if st.session_state.team_to_delete:
        target_tid = st.session_state.team_to_delete["id"]
        target_name = st.session_state.team_to_delete["name"]
        st.markdown(
            f"""
            <div class="mt-card" style="border: 2px solid #EF4444; background: rgba(239, 68, 68, 0.06);">
                <div style="font-weight: 800; color: #EF4444; font-size: 1.15rem; margin-bottom: 0.4rem;">
                    ⚠️ Permanent Deletion Warning: {target_name}
                </div>
                <div style="font-size: 0.88rem; color: #64748B; margin-bottom: 1rem;">
                    Deleting this team will completely remove the team along with all its meetings,
                    extracted proposals, committed action items, version history, and reminder drafts.
                    This operation cannot be undone.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        c_del_conf, c_del_cancel, _ = st.columns([1.2, 1, 2])
        with c_del_conf:
            if st.button("Confirm Delete Team", type="primary", key="confirm_delete_btn"):
                try:
                    client.delete_team(target_tid)
                    st.success(f"Team '{target_name}' deleted successfully.")
                    if st.session_state.selected_team_id == target_tid:
                        st.session_state.selected_team_id = None
                        st.session_state.selected_team_name = None
                    st.session_state.team_to_delete = None
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to delete team: {exc}")
        with c_del_cancel:
            if st.button("Cancel", key="cancel_delete_btn"):
                st.session_state.team_to_delete = None
                st.rerun()

        st.markdown("<div style='height: 1.5rem;'></div>", unsafe_allow_html=True)

    col_t_list, col_t_create = st.columns([1.2, 0.8])

    with col_t_list:
        st.markdown(
            """
            <div class="mt-card-title">Existing Teams</div>
            <div class="mt-card-subtitle">Select an active team to inspect, review proposals, or manage actions.</div>
            """,
            unsafe_allow_html=True,
        )
        if not teams_list:
            st.info("No teams have been created yet. Use the form on the right to add your first team.")
        else:
            for t in teams_list:
                t_id = t["team_id"]
                t_name = t["name"]
                t_supervisor = t.get("supervisor") or "None assigned"
                members = t.get("members", [])
                is_selected = t_id == st.session_state.selected_team_id

                active_border = "border: 2px solid #7C3AED;" if is_selected else ""
                active_badge = "<span class='mt-badge badge-green' style='margin-left: 0.5rem;'>Active</span>" if is_selected else ""

                st.markdown(
                    f"""
                    <div class="mt-card" style="{active_border} margin-bottom: 0.85rem; padding: 1.1rem;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-size: 1.05rem; font-weight: 700;">{t_name} {active_badge}</span>
                            <span class="code-pill">ID: {t_id[:8]}...</span>
                        </div>
                        <div style="font-size: 0.82rem; color: #94A3B8; margin-top: 0.35rem;">
                            <strong>Supervisor:</strong> {t_supervisor} &bull; <strong>Members:</strong> {len(members)}
                        </div>
                        <div style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.3rem;">
                            {"".join([f"<span class='mt-badge badge-purple'>{m}</span>" for m in members]) if members else "<span style='font-size: 0.78rem; color: #94A3B8;'>No members registered</span>"}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                c_btn_select, c_btn_delete, _ = st.columns([1.2, 1, 1.8])
                with c_btn_select:
                    if not is_selected:
                        if st.button("Set Active", key=f"sel_team_{t_id}"):
                            st.session_state.selected_team_id = t_id
                            st.session_state.selected_team_name = t_name
                            st.session_state.active_cycle_id = None
                            st.rerun()
                with c_btn_delete:
                    if st.button("🗑️ Delete", key=f"del_team_prompt_{t_id}"):
                        st.session_state.team_to_delete = {"id": t_id, "name": t_name}
                        st.rerun()

                st.markdown("<div style='height: 0.6rem;'></div>", unsafe_allow_html=True)

    with col_t_create:
        st.markdown(
            """
            <div class="mt-card">
                <div class="mt-card-title">➕ Create New Team</div>
                <div class="mt-card-subtitle">Set up student members for action ownership validation</div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("new_team_form", clear_on_submit=True):
            new_name = st.text_input("Team Name *", placeholder="e.g. HealthAI FYP Group")
            new_supervisor = st.text_input("Supervisor (Optional)", placeholder="e.g. Dr. Asim")
            new_members_raw = st.text_area(
                "Members *",
                placeholder="Bilal\nAmna\nSara\n(one per line or comma-separated)",
                help="Team members will be validated during action ownership extraction.",
            )
            create_btn = st.form_submit_button("Create Team", type="primary")

            if create_btn:
                if not new_name.strip():
                    st.error("Team name is required.")
                elif not new_members_raw.strip():
                    st.error("At least one student member is required.")
                else:
                    members_parsed = [
                        m.strip()
                        for m in new_members_raw.replace(",", "\n").splitlines()
                        if m.strip()
                    ]
                    try:
                        res = client.create_team(
                            name=new_name.strip(),
                            members=members_parsed,
                            supervisor=new_supervisor.strip() if new_supervisor else None,
                        )
                        st.success(f"Team '{res['name']}' created successfully!")
                        st.session_state.selected_team_id = res["team_id"]
                        st.session_state.selected_team_name = res["name"]
                        st.session_state.active_cycle_id = None
                        st.rerun()
                    except ApiError as exc:
                        st.error(f"Error creating team: {exc.detail}")

        st.markdown("</div>", unsafe_allow_html=True)


# ===========================================================================
# PAGE 3: MEETING NOTES
# ===========================================================================
elif st.session_state.current_page == "Meeting Notes":
    team_id = st.session_state.selected_team_id
    team_name = st.session_state.selected_team_name

    st.markdown(
        """
        <div class="mt-card">
            <div class="mt-card-title">📝 Ingest & Process Meeting Notes</div>
            <div class="mt-card-subtitle">
                Workflow: <strong>1. Upload / Paste Notes</strong> ➔ <strong>2. AI Extraction</strong> ➔ <strong>3. Human Approval Gate</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not team_id:
        st.warning("Please select or create an active team in the **Teams** page first.")
    else:
        col_ingest, col_hist = st.columns([1.1, 0.9])

        with col_ingest:
            st.markdown(
                f"""
                <div class="mt-card">
                    <div style="font-weight: 700; margin-bottom: 0.6rem;">Processing Context: <span style="color: #7C3AED;">{team_name}</span></div>
                """,
                unsafe_allow_html=True,
            )

            # File upload or direct paste
            uploaded_file = st.file_uploader(
                "Upload Plain-Text Meeting Notes (.txt)",
                type=["txt"],
                help="Uploaded file should have numbered lines (e.g. 1. Bilal: I will collect leaf images by Friday)",
            )
            pasted_text = st.text_area(
                "Or Paste Numbered Meeting Notes Directly",
                height=150,
                placeholder="Meeting 1 | 2026-10-05\n1. Bilal: I will collect 500 more leaf images by Friday.\n2. Amna: I will label the dataset by Monday.",
            )

            c_date, c_mem = st.columns(2)
            with c_date:
                as_of_date = st.date_input("Meeting Date (As-Of)", value=date.today())
            with c_mem:
                memory_enabled = st.toggle(
                    "Enable Memory",
                    value=True,
                    help="When ON, approved proposals update persistent SQLite memory. When OFF (Dry Run), extraction runs without modifying persistent records.",
                )

            st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)

            has_content = (uploaded_file is not None) or bool(pasted_text.strip())

            process_btn = st.button(
                "🚀 Process Notes with Local Ollama",
                type="primary",
                disabled=not has_content,
                help="Upload a file or paste text to enable processing.",
            )

            if process_btn:
                content_to_process = ""
                file_name = "meeting_notes.txt"

                if uploaded_file is not None:
                    content_to_process = uploaded_file.getvalue().decode("utf-8", errors="replace")
                    file_name = uploaded_file.name
                elif pasted_text.strip():
                    content_to_process = pasted_text.strip()
                    file_name = f"notes_{as_of_date.isoformat()}.txt"

                with st.spinner("Analyzing notes with Ollama (extracting actions, verifying quotes & checking deadlines)..."):
                    try:
                        report = client.ingest_notes(
                            team_id=team_id,
                            file_name=file_name,
                            content=content_to_process,
                            as_of=as_of_date.isoformat(),
                            memory_enabled=memory_enabled,
                        )
                        st.session_state.last_report = report
                        if report.get("cycle_id"):
                            st.session_state.active_cycle_id = report["cycle_id"]
                        st.success(f"Processing complete! Generated Cycle: {report.get('cycle_id')}")
                    except ApiError as exc:
                        st.error(f"Processing failed: {exc.detail}")
                        st.info("Tip: Verify that Ollama is running (`ollama list`) and model `qwen2.5:1.5b` is downloaded.")

            st.markdown("</div>", unsafe_allow_html=True)

        with col_hist:
            st.markdown(
                """
                <div class="mt-card">
                    <div class="mt-card-title">📜 Team Ingestion History</div>
                    <div class="mt-card-subtitle">Existing meetings processed for this team</div>
                """,
                unsafe_allow_html=True,
            )
            try:
                meetings = client.list_meetings(team_id=team_id)
            except Exception:
                meetings = []

            if meetings:
                for mtg in meetings:
                    st.markdown(
                        f"""
                        <div style="padding: 0.65rem 0; border-bottom: 1px dashed rgba(124, 58, 237, 0.15);">
                            <div style="font-weight: 600; font-size: 0.9rem;">{mtg.get('file_name')}</div>
                            <div style="font-size: 0.78rem; color: #94A3B8;">
                                Date: {mtg.get('meeting_date') or 'N/A'} &bull; Hash: <span class="code-pill">{(mtg.get('file_hash') or '')[:10]}...</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No meetings ingested yet for this team.")

            st.markdown("</div>", unsafe_allow_html=True)

        # Show Processing Report
        report = st.session_state.last_report
        if report:
            st.markdown(
                f"""
                <div class="mt-card" style="border-left: 4px solid #10B981;">
                    <div class="mt-card-title">✨ Cycle Summary: {report.get('status', '').upper()}</div>
                    <div class="mt-card-subtitle">Cycle ID: <span class="code-pill">{report.get('cycle_id')}</span></div>
                """,
                unsafe_allow_html=True,
            )

            warnings = report.get("warnings", [])
            if warnings:
                with st.expander("⚠️ Cycle Warnings / Neutralized Content", expanded=False):
                    for w in warnings:
                        st.write(f"- {w}")

            proposals = report.get("proposals", [])
            st.write(f"**Extracted Action Proposals ({len(proposals)}):**")
            if proposals:
                t_data = []
                for p in proposals:
                    t_data.append(
                        {
                            "Outcome": p.get("outcome"),
                            "Description": p.get("description"),
                            "Owner": p.get("owner") or "Unassigned",
                            "Due Date": p.get("due_date") or "None",
                            "Verified Line": p.get("evidence_line") or "N/A",
                            "Agent Reason": p.get("reason"),
                        }
                    )
                st.dataframe(t_data, use_container_width=True)

                if st.button("⚖️ Proceed to Proposal Review", type="primary"):
                    st.session_state.current_page = "Proposal Review"
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)


# ===========================================================================
# PAGE 4: PROPOSAL REVIEW
# ===========================================================================
elif st.session_state.current_page == "Proposal Review":
    team_id = st.session_state.selected_team_id
    team_name = st.session_state.selected_team_name

    st.markdown(
        """
        <div class="mt-card">
            <div class="mt-card-title">⚖️ Human Approval Gate: Proposal Review</div>
            <div class="mt-card-subtitle">
                Inspect AI suggestions before updating persistent memory. Approve, edit, or reject each proposal.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not team_id:
        st.warning("Please select an active team in the **Teams** page first.")
    else:
        active_cycle_id = st.session_state.active_cycle_id
        c_cycle, _ = st.columns([1.5, 1])
        with c_cycle:
            cycle_input = st.text_input(
                "Cycle ID to Review",
                value=active_cycle_id or "",
                placeholder="e.g. 7efdc804-... or team-1-mtg-1",
                help="Enter or paste the Cycle ID generated during meeting notes ingestion.",
            )
            if cycle_input and cycle_input != st.session_state.active_cycle_id:
                st.session_state.active_cycle_id = cycle_input
                st.rerun()

        if st.session_state.active_cycle_id:
            try:
                proposals = client.list_proposals(
                    team_id=team_id,
                    cycle_id=st.session_state.active_cycle_id,
                )
            except ApiError as exc:
                st.error(f"Error loading proposals: {exc.detail}")
                proposals = []

            if proposals:
                try:
                    team_members = [m["name"] for m in client.list_members(team_id)]
                except Exception:
                    team_members = []

                pending = [p for p in proposals if p.get("status") == "pending"]
                decided = [p for p in proposals if p.get("status") in ("approved", "edited", "rejected")]

                # Header counts
                st.markdown(
                    f"""
                    <div style="display: flex; gap: 1rem; margin-bottom: 1rem;">
                        <span class="mt-badge badge-amber" style="font-size: 0.85rem;">Pending Review: {len(pending)}</span>
                        <span class="mt-badge badge-green" style="font-size: 0.85rem;">Decided: {len(decided)}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Pending Proposals Cards
                if pending:
                    st.markdown("<div class='mt-card-title'>Pending Proposals</div>", unsafe_allow_html=True)
                    for idx, p in enumerate(pending):
                        prop_id = p["proposal_id"]
                        outcome = p.get("outcome", "new_action")
                        payload = json.loads(p.get("payload_json", "{}"))

                        st.markdown(
                            f"""
                            <div class="mt-card" style="border-left: 4px solid #7C3AED; margin-bottom: 0.9rem;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
                                    <span style="font-weight: 700; font-size: 1rem;">Proposal #{idx + 1}: {payload.get('description', '')}</span>
                                    <span class="mt-badge badge-purple">{outcome}</span>
                                </div>
                                <div style="font-size: 0.85rem; color: #94A3B8; margin-bottom: 0.5rem;">
                                    👤 <strong>Owner:</strong> {payload.get('owner') or 'Unassigned'} &bull;
                                    📅 <strong>Due Date:</strong> {payload.get('due_date') or 'None'} &bull;
                                    🔍 <strong>Evidence Line:</strong> {payload.get('evidence_line') or 'N/A'}
                                </div>
                                <div style="font-size: 0.82rem; font-style: italic; background: rgba(124, 58, 237, 0.05); padding: 0.5rem 0.8rem; border-radius: 8px; margin-bottom: 0.5rem;">
                                    "{payload.get('evidence_quote') or 'No quote provided'}"
                                </div>
                                <div style="font-size: 0.8rem; color: #64748B;">
                                    <strong>Agent Reason:</strong> {payload.get('reason') or 'N/A'}
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        c_app, c_edit, c_rej, _ = st.columns([1, 1.2, 1, 2.5])
                        with c_app:
                            if st.button("✅ Approve", key=f"app_{prop_id}", type="primary"):
                                try:
                                    client.decide_proposal(team_id=team_id, proposal_id=prop_id, decision="approve")
                                    st.success("Approved!")
                                    st.rerun()
                                except ApiError as exc:
                                    st.error(exc.detail)

                        with c_edit:
                            with st.popover("✏️ Edit & Approve"):
                                if team_members:
                                    st.caption(f"Team members: {', '.join(team_members)}")
                                ed_desc = st.text_input("Description", value=payload.get("description") or "", key=f"ed_desc_{prop_id}")
                                ed_owner = st.text_input("Owner", value=payload.get("owner") or "", key=f"ed_owner_{prop_id}")
                                ed_due = st.text_input("Due Date", value=payload.get("due_date") or "", key=f"ed_due_{prop_id}")
                                ed_comm = st.text_input("Comment", key=f"ed_comm_{prop_id}", placeholder="Correction notes")
                                if st.button("Save & Approve", key=f"save_ed_{prop_id}"):
                                    new_payload = dict(payload)
                                    new_payload["description"] = ed_desc.strip() if ed_desc.strip() else None
                                    new_payload["owner"] = ed_owner.strip() if ed_owner.strip() else None
                                    new_payload["due_date"] = ed_due.strip() if ed_due.strip() else None
                                    try:
                                        client.decide_proposal(
                                            team_id=team_id,
                                            proposal_id=prop_id,
                                            decision="edit",
                                            user_comment=ed_comm or "Edited by reviewer",
                                            edited_payload=new_payload,
                                        )
                                        st.success("Edited and approved!")
                                        st.rerun()
                                    except ApiError as exc:
                                        st.error(exc.detail)

                        with c_rej:
                            with st.popover("❌ Reject"):
                                rej_reason = st.text_input("Reason", key=f"rej_res_{prop_id}", placeholder="Why rejected?")
                                if st.button("Confirm Reject", key=f"conf_rej_{prop_id}"):
                                    try:
                                        client.decide_proposal(
                                            team_id=team_id,
                                            proposal_id=prop_id,
                                            decision="reject",
                                            user_comment=rej_reason or "Rejected by user",
                                        )
                                        st.warning("Rejected.")
                                        st.rerun()
                                    except ApiError as exc:
                                        st.error(exc.detail)

                        st.markdown("<div style='height: 0.8rem;'></div>", unsafe_allow_html=True)
                else:
                    st.success("All proposals in this cycle have been reviewed!")

                # Commitment Gate
                st.markdown(
                    """
                    <div class="mt-card" style="margin-top: 1.5rem; background: linear-gradient(135deg, rgba(16, 185, 129, 0.05), rgba(124, 58, 237, 0.05)); border: 1px solid #10B981;">
                        <div class="mt-card-title">🚀 Commitment Gate</div>
                        <div class="mt-card-subtitle">
                            Persist approved decisions into versioned action memory. Rejected or pending proposals will never modify the committed state.
                        </div>
                    """,
                    unsafe_allow_html=True,
                )
                can_commit = len(decided) > 0
                if st.button("Commit Approved Decisions to Memory", type="primary", disabled=not can_commit):
                    with st.spinner("Committing to SQLite persistent memory..."):
                        try:
                            commit_res = client.commit_proposals(team_id=team_id, cycle_id=st.session_state.active_cycle_id)
                            st.success(f"Committed {len(commit_res)} decisions to persistent memory!")
                            st.rerun()
                        except ApiError as exc:
                            st.error(f"Commit failed: {exc.detail}")

                st.markdown("</div>", unsafe_allow_html=True)

                # Decided Proposals Table
                if decided:
                    st.markdown("<div class='mt-card-title' style='margin-top: 1.5rem;'>Decided Proposals</div>", unsafe_allow_html=True)
                    dec_table = []
                    for d in decided:
                        p_val = json.loads(d.get("payload_json", "{}"))
                        dec_table.append(
                            {
                                "Status": d.get("status"),
                                "Outcome": d.get("outcome"),
                                "Description": p_val.get("description"),
                                "Owner": p_val.get("owner"),
                                "Committed?": "Yes" if d.get("committed_at") else "No",
                            }
                        )
                    st.dataframe(dec_table, use_container_width=True)
            else:
                st.info("No proposals found for this cycle.")
        else:
            st.info("Enter or select a Cycle ID from the Meeting Notes tab to review proposals.")


# ===========================================================================
# PAGE 5: ACTION REGISTER
# ===========================================================================
elif st.session_state.current_page == "Action Register":
    team_id = st.session_state.selected_team_id
    team_name = st.session_state.selected_team_name

    st.markdown(
        """
        <div class="mt-card">
            <div class="mt-card-title">📋 Action Register & Versioned Memory</div>
            <div class="mt-card-subtitle">
                Current persistent register of team commitments with complete auditable history and manual correction capabilities.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not team_id:
        st.warning("Please select an active team in the **Teams** page first.")
    else:
        include_done = st.checkbox("Include completed actions ('done')", value=True)

        try:
            actions = client.list_actions(team_id=team_id, include_done=include_done)
        except ApiError as exc:
            st.error(f"Could not load actions: {exc.detail}")
            actions = []

        if actions:
            act_table = []
            for a in actions:
                act_table.append(
                    {
                        "Code": a.get("action_code"),
                        "Status": a.get("status"),
                        "Description": a.get("description"),
                        "Owner": a.get("owner") or "Unassigned",
                        "Due Date": a.get("due_date") or "None",
                        "Blocked Reason": a.get("blocked_reason") or "",
                        "Version": a.get("version_no"),
                        "Valid From": (a.get("valid_from") or "")[:10],
                    }
                )
            st.dataframe(act_table, use_container_width=True)

            # History Inspector and Correction Form
            st.markdown(
                """
                <div class="mt-card" style="margin-top: 1.5rem;">
                    <div class="mt-card-title">🔍 Inspect Action & Apply Audited Correction</div>
                    <div class="mt-card-subtitle">View past versions or manually adjust fields (creates a new version in SQLite)</div>
                """,
                unsafe_allow_html=True,
            )

            action_dict = {f"{a['action_code']}: {a['description'][:45]}": a for a in actions}
            selected_label = st.selectbox("Select Action", options=list(action_dict.keys()))

            if selected_label:
                sel_action = action_dict[selected_label]
                sel_action_id = sel_action["action_id"]

                # Version history
                try:
                    history = client.get_action_history(team_id=team_id, action_id=sel_action_id)
                    hist_data = []
                    for h in history:
                        hist_data.append(
                            {
                                "Version": h.get("version_no"),
                                "Status": h.get("status"),
                                "Owner": h.get("owner") or "None",
                                "Due Date": h.get("due_date") or "None",
                                "Changed By": h.get("changed_by"),
                                "Current?": "Yes" if h.get("is_current") else "Superseded",
                                "Valid From": (h.get("valid_from") or "")[:19],
                                "Superseded At": (h.get("superseded_at") or "")[:19] or "-",
                            }
                        )
                    st.write(f"**Version History for [{sel_action['action_code']}]:**")
                    st.dataframe(hist_data, use_container_width=True)
                except Exception as exc:
                    st.warning(f"Could not load version history: {exc}")

                # Correction form
                with st.expander(f"Apply Correction to [{sel_action['action_code']}]"):
                    st.caption("Corrections create a new auditable version without deleting historical records.")
                    with st.form("correct_form", clear_on_submit=True):
                        c_field = st.selectbox("Field to Update", options=["owner", "due_date", "status"])
                        c_val = st.text_input("New Value *", placeholder="e.g. Bilal or 2026-11-01 or done")
                        c_reason = st.text_input("Reason / Comment", placeholder="Justification for manual correction")
                        c_sub = st.form_submit_button("Submit Correction", type="primary")

                        if c_sub:
                            if not c_val.strip():
                                st.error("New value is required.")
                            else:
                                try:
                                    updated = client.correct_action(
                                        team_id=team_id,
                                        action_id=sel_action_id,
                                        field=c_field,
                                        value=c_val.strip(),
                                        comment=c_reason.strip() if c_reason else None,
                                    )
                                    st.success(f"Action updated to version {updated['version_no']}!")
                                    st.rerun()
                                except ApiError as exc:
                                    st.error(f"Correction failed: {exc.detail}")

            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("No actions recorded for this team yet. Ingest meeting notes to extract actions.")


# ===========================================================================
# PAGE 6: EXPORTS & REMINDERS
# ===========================================================================
elif st.session_state.current_page == "Exports & Reminders":
    team_id = st.session_state.selected_team_id
    team_name = st.session_state.selected_team_name

    st.markdown(
        """
        <div class="mt-card">
            <div class="mt-card-title">📦 Exports & Reminders</div>
            <div class="mt-card-subtitle">
                Download Excel action registers and generate persistent UNSENT reminder drafts for supervisor review.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not team_id:
        st.warning("Please select an active team in the **Teams** page first.")
    else:
        col_exp_left, col_exp_right = st.columns(2)

        # Excel Action Register
        with col_exp_left:
            st.markdown(
                """
                <div class="mt-card">
                    <div class="mt-card-title">📊 Excel Action Register</div>
                    <div class="mt-card-subtitle">Complete export with two sheets: 'Action Register' and 'History' audit log</div>
                """,
                unsafe_allow_html=True,
            )
            as_of_export = st.date_input("As-Of Date for Overdue Calculations", value=date.today())

            try:
                excel_bytes = client.download_register(
                    team_id=team_id,
                    as_of=as_of_export.isoformat(),
                )
                safe_name = team_name.lower().replace(" ", "_") if team_name else "team"
                st.download_button(
                    label="📥 Download Action Register (.xlsx)",
                    data=excel_bytes,
                    file_name=f"action_register_{safe_name}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                )
            except ApiError as exc:
                st.error(f"Could not generate Excel register: {exc.detail}")

            st.markdown("</div>", unsafe_allow_html=True)

        # Reminder Drafts
        with col_exp_right:
            st.markdown(
                """
                <div class="mt-card">
                    <div class="mt-card-title">✉️ Reminder Drafts</div>
                    <div class="mt-card-subtitle">
                        <span class="mt-badge badge-amber">Strict Rule: UNSENT Drafts Only</span>
                        <div style="margin-top: 0.35rem;">Reminders are never automatically sent. Drafts are generated for supervisor review only.</div>
                    </div>
                """,
                unsafe_allow_html=True,
            )

            if st.session_state.active_cycle_id:
                if st.button("Generate Reminder Drafts for Active Cycle", type="primary"):
                    try:
                        new_rems = client.generate_reminders(
                            team_id=team_id,
                            cycle_id=st.session_state.active_cycle_id,
                        )
                        st.success(f"Generated {len(new_rems)} reminder draft(s)!")
                        st.rerun()
                    except ApiError as exc:
                        st.error(f"Failed to generate reminders: {exc.detail}")

            try:
                reminders = client.list_reminders(team_id=team_id)
            except Exception:
                reminders = []

            if reminders:
                st.write(f"**Saved Reminder Drafts ({len(reminders)}):**")
                for r in reminders:
                    with st.expander(f"Draft for {r.get('recipient_name', 'Student')} (Status: {r.get('status')})"):
                        st.caption(f"Idempotency Key: {r.get('idempotency_key')}")
                        st.text_area(
                            "Message Content",
                            value=r.get("draft_text", ""),
                            height=120,
                            disabled=True,
                            key=f"rem_{r.get('reminder_id')}",
                        )
            else:
                st.info("No reminder drafts generated yet.")

            st.markdown("</div>", unsafe_allow_html=True)


# ===========================================================================
# 9. REPOSITIONED FLOATING MASCOT ("TRACKY")
# ===========================================================================
mascot_messages = {
    "Dashboard": "Let's see what needs your attention!",
    "Teams": "Managing groups is easy! Every team gets isolated actions.",
    "Meeting Notes": "Ready to turn your notes into action items?",
    "Proposal Review": "Let's review these suggestions together.",
    "Action Register": "Here's what your team needs to get done.",
    "Exports & Reminders": "Download clean Excel sheets! Reminders stay UNSENT.",
}
current_mascot_msg = mascot_messages.get(st.session_state.current_page, "Ready to track your next steps?")

st.markdown(
    f'<a href="?tutorial=true" target="_self" class="mt-floating-mascot-box" title="Click to open MeetTrack Interactive Guide">'
    f'<div class="mt-mascot-bubble">'
    f'<strong>Tracky:</strong> {current_mascot_msg}'
    f'<div style="font-size: 0.7rem; color: #7C3AED; font-weight: 700; margin-top: 2px;">💡 Click for Interactive Tour</div>'
    f'</div>'
    f'<div class="mt-mascot-avatar-btn">{render_mascot_svg(size=44)}</div>'
    f'</a>',
    unsafe_allow_html=True,
)
