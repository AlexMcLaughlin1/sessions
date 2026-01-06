from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import json
import re

import pandas as pd
import streamlit as st

CSV_PATH = Path(__file__).with_name("sessions_temp.csv")
STATE_PATH = Path(__file__).with_name("plan_state.json")
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SWIM_DISTANCE_KM = 2.0
STATE_VERSION = 1


@st.cache_data
def load_plan(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def date_label(day: date) -> str:
    return f"{DAY_NAMES[day.weekday()]} {day.isoformat()}"


def completion_key(week_idx: int, session_col: str) -> str:
    slug = session_col.lower().replace(" ", "_")
    return f"completed_{week_idx}_{slug}"


def planned_key(week_idx: int, session_col: str) -> str:
    slug = session_col.lower().replace(" ", "_")
    return f"planned_{week_idx}_{slug}"


def align_to_monday(day: date) -> date:
    offset = (7 - day.weekday()) % 7
    return day + timedelta(days=offset)


def extract_km(segment: str) -> float:
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*km", segment)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        return (low + high) / 2

    values = [float(val) for val in re.findall(r"(\d+(?:\.\d+)?)\s*km", segment)]
    return sum(values)


def session_distances(session_text: str) -> dict[str, float]:
    distances = {"swim": 0.0, "bike": 0.0, "run": 0.0}
    text = session_text.lower()
    for segment in re.split(r"\+", text):
        segment = segment.strip()
        if not segment:
            continue
        if "swim" in segment:
            distances["swim"] += SWIM_DISTANCE_KM
        if "bike" in segment or "cycle" in segment:
            distances["bike"] += extract_km(segment)
        if "run" in segment:
            distances["run"] += extract_km(segment)
    return distances


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if data.get("version") != STATE_VERSION:
        return {}
    return data.get("state", {})


def save_state(state: dict) -> None:
    payload = {
        "version": STATE_VERSION,
        "saved_at": date.today().isoformat(),
        "state": state,
    }
    try:
        STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        st.warning("Unable to save state to disk.")


st.set_page_config(page_title="Training Plan Tracker", layout="wide")
st.title("Training Plan Tracker")
st.markdown(
    """
    <style>
    .session-cell {
        display: block;
        width: 100%;
        padding: 0.4rem 0.5rem;
        border-radius: 0.4rem;
        font-weight: 600;
        border: 1px solid #d1d5db;
        margin-bottom: 0.35rem;
        box-sizing: border-box;
    }
    .session-cell.completed {
        background-color: #15803d;
        color: #ffffff;
        border-color: #15803d;
    }
    .session-cell.missed {
        background-color: #b91c1c;
        color: #ffffff;
        border-color: #b91c1c;
    }
    .session-cell.pending {
        background-color: #f3f4f6;
        color: #111827;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if not CSV_PATH.exists():
    st.error(f"CSV not found at {CSV_PATH}")
    st.stop()

plan_df = load_plan(CSV_PATH)
plan_df.columns = [str(col).strip() for col in plan_df.columns]

if "Week Commencing" not in plan_df.columns:
    st.error("CSV needs a 'Week Commencing' column.")
    st.stop()

session_cols = [col for col in plan_df.columns if col.lower().startswith("session")]
if not session_cols:
    st.error("CSV needs at least one session column like 'Session 1'.")
    st.stop()

if plan_df.empty:
    st.error("CSV has no rows.")
    st.stop()

plan_df["Week Commencing"] = pd.to_datetime(
    plan_df["Week Commencing"], dayfirst=True, errors="coerce"
).dt.date

if plan_df["Week Commencing"].isna().any():
    st.error("One or more 'Week Commencing' values could not be parsed as dates.")
    st.stop()

raw_week_starts = plan_df["Week Commencing"].tolist()
base_start = align_to_monday(raw_week_starts[0])
week_starts = [base_start + timedelta(days=7 * idx) for idx in range(len(plan_df))]
plan_df["Week Commencing"] = week_starts
today = date.today()

if "state_loaded" not in st.session_state:
    restored_state = load_state()
    for key, value in restored_state.items():
        if key not in st.session_state:
            st.session_state[key] = value
    st.session_state["state_loaded"] = True

plan_start = week_starts[0]
plan_end = week_starts[-1] + timedelta(days=6)
plan_days = max(1, (plan_end - plan_start).days + 1)

current_week_idx = 0
for idx, week_start in enumerate(week_starts):
    if week_start <= today <= week_start + timedelta(days=6):
        current_week_idx = idx
        break
else:
    if today > plan_end:
        current_week_idx = len(week_starts) - 1

total_sessions = len(plan_df) * len(session_cols)
completed_count = 0
missed_count = 0
swim_km = 0.0
bike_km = 0.0
run_km = 0.0
gym_sessions = 0

for week_idx, row in plan_df.iterrows():
    week_start = week_starts[week_idx]
    week_end = week_start + timedelta(days=6)
    for session_col in session_cols:
        session_text = ""
        if session_col in row and not pd.isna(row[session_col]):
            session_text = str(row[session_col])

        c_key = completion_key(week_idx, session_col)
        if st.session_state.get(c_key, False):
            completed_count += 1
            distances = session_distances(session_text)
            swim_km += distances["swim"]
            bike_km += distances["bike"]
            run_km += distances["run"]
            if "gym" in session_text.lower():
                gym_sessions += 1
        elif week_end < today:
            missed_count += 1

completed_pct = 0.0 if total_sessions == 0 else (completed_count / total_sessions) * 100
missed_pct = 0.0 if total_sessions == 0 else (missed_count / total_sessions) * 100
if today <= plan_start:
    plan_progress_pct = 0.0
elif today >= plan_end:
    plan_progress_pct = 100.0
else:
    plan_progress_pct = ((today - plan_start).days / plan_days) * 100

days_remaining = max(0, (plan_end - today).days)

st.subheader("Plan overview")
overview_cols = st.columns(4)
overview_cols[0].metric(
    "Sessions completed", f"{completed_count} / {total_sessions}", f"{completed_pct:.1f}%"
)
overview_cols[1].metric("Sessions missed", f"{missed_pct:.1f}%")
overview_cols[2].metric("Plan progress", f"{plan_progress_pct:.1f}%")
overview_cols[3].metric("Days till complete", str(days_remaining))

st.subheader("Discipline totals")
distance_cols = st.columns(4)
distance_cols[0].metric("Swim completed (km)", f"{swim_km:.1f}")
distance_cols[1].metric("Bike completed (km)", f"{bike_km:.1f}")
distance_cols[2].metric("Run completed (km)", f"{run_km:.1f}")
distance_cols[3].metric("Gym sessions completed", str(gym_sessions))

st.subheader("Training plan table")
header_cols = st.columns([1, 1.5] + [2] * len(session_cols))
header_cols[0].markdown("**Week**")
header_cols[1].markdown("**Week commencing**")
for idx, session_col in enumerate(session_cols):
    header_cols[idx + 2].markdown(f"**{session_col}**")

for week_idx, row in plan_df.iterrows():
    row_cols = st.columns([1, 1.5] + [2] * len(session_cols))
    week_label = row.get("Week", week_idx + 1)
    if pd.isna(week_label):
        week_label = week_idx + 1
    if week_idx == current_week_idx:
        row_cols[0].write(f"{week_label} (current)")
    else:
        row_cols[0].write(str(week_label))

    week_start = week_starts[week_idx]
    week_end = week_start + timedelta(days=6)
    row_cols[1].write(week_start.isoformat())
    week_dates = [week_start + timedelta(days=i) for i in range(7)]
    date_options = ["Unplanned"] + [date_label(day) for day in week_dates]

    for session_offset, session_col in enumerate(session_cols):
        cell = row_cols[session_offset + 2]
        session_text = ""
        if session_col in row and not pd.isna(row[session_col]):
            session_text = str(row[session_col])

        c_key = completion_key(week_idx, session_col)
        completed = st.session_state.get(c_key, False)
        missed = (not completed) and (week_end < today)
        status_class = "completed" if completed else "missed" if missed else "pending"

        cell.markdown(
            f"<div class='session-cell {status_class}'>{session_text}</div>",
            unsafe_allow_html=True,
        )

        p_key = planned_key(week_idx, session_col)
        select_key = f"{p_key}_select"
        existing_iso = st.session_state.get(p_key)
        default_index = 0
        if existing_iso:
            try:
                existing_date = date.fromisoformat(existing_iso)
                if existing_date in week_dates:
                    default_index = week_dates.index(existing_date) + 1
            except ValueError:
                default_index = 0

        if select_key not in st.session_state:
            st.session_state[select_key] = date_options[default_index]

        selected_label = cell.selectbox(
            "Plan day",
            options=date_options,
            key=select_key,
            label_visibility="collapsed",
        )

        if selected_label == "Unplanned":
            st.session_state.pop(p_key, None)
        else:
            chosen_date = week_dates[date_options.index(selected_label) - 1]
            st.session_state[p_key] = chosen_date.isoformat()

        cell.checkbox("Done", key=c_key)

persisted_state = {}
for week_idx in range(len(plan_df)):
    for session_col in session_cols:
        c_key = completion_key(week_idx, session_col)
        if c_key in st.session_state:
            persisted_state[c_key] = bool(st.session_state.get(c_key, False))
        p_key = planned_key(week_idx, session_col)
        if p_key in st.session_state:
            persisted_state[p_key] = st.session_state.get(p_key)

if st.session_state.get("state_loaded"):
    save_state(persisted_state)
