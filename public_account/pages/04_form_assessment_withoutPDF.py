"""
────────────────────────────────────────────────────────────────────────────────
MCQ Form-only Page (LLM & OCR removed)
────────────────────────────────────────────────────────────────────────────────
This page only provides session management, company selection and a form to
collect MCQ answers (interactive ESG question set or load from a file).
Collected answers are saved to the active session inputs/answers.json and a
simple scoring summary (raw points) is displayed with download options.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_compat import get_query_params
from _page_descriptions import render_page_description

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MCQ Form (No LLM / No OCR)",
    page_icon="📝",
    layout="wide",
)
render_page_description(__file__)

# ── Paths & env ────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parents[1]
DATA_DIR      = BASE_DIR / "data"
USER_DATA_DIR = BASE_DIR / "user_data"
LOG_DIR       = BASE_DIR / "logs"

for _d in (DATA_DIR, USER_DATA_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

CHOICE_SCORE           = {"A": 3, "B": 2, "C": 1, "D": 0, "": 0}
MAX_SCORE_PER_QUESTION = 3

ESG_MCQ_JSON = DATA_DIR / "esg_mcq.json"


def _load_esg_mcq() -> list[dict]:
    if ESG_MCQ_JSON.exists():
        try:
            data = json.loads(ESG_MCQ_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return []


ESG_MCQ: list[dict] = _load_esg_mcq()

# ══════════════════════════════════════════════════════════════════════════════
# SESSION FILESYSTEM HELPERS (minimal)
# ══════════════════════════════════════════════════════════════════════════════

def get_user_dir(username: str) -> Path:
    return USER_DATA_DIR / username


def get_sessions_dir(username: str) -> Path:
    return get_user_dir(username) / "sessions"


def create_new_session(username: str) -> tuple[str, Path]:
    ts       = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    sess_dir = get_sessions_dir(username) / ts
    for sub in ("inputs", "outputs", "logs"):
        (sess_dir / sub).mkdir(parents=True, exist_ok=True)

    meta = {
        "session_id":  ts,
        "username":    username,
        "created_at":  datetime.utcnow().isoformat() + "Z",
        "status":      "created",
        "doc_count":   0,
        "company":     "",
        "answer_mode": "",
    }
    (sess_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return ts, sess_dir


def list_user_sessions(username: str) -> list[dict]:
    sessions_dir = get_sessions_dir(username)
    if not sessions_dir.exists():
        return []
    result = []
    for p in sorted(sessions_dir.iterdir(), reverse=True):
        if not p.is_dir():
            continue
        meta_file = p / "metadata.json"
        if meta_file.exists():
            try:
                m = json.loads(meta_file.read_text(encoding="utf-8"))
                result.append(m)
            except Exception:
                result.append({"session_id": p.name, "created_at": p.name})
        else:
            result.append({"session_id": p.name, "created_at": p.name})
    return result


def get_session_path(username: str, session_id: str) -> Path:
    return get_sessions_dir(username) / session_id


def update_session_meta(sess_dir: Path, updates: dict):
    meta_file = sess_dir / "metadata.json"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    except Exception:
        meta = {}
    meta.update(updates)
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def save_json(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_name(name: str) -> str:
    if not name:
        return "file"
    return "".join(c if c.isalnum() or c in " ._-" else "_" for c in name).strip()


# ══════════════════════════════════════════════════════════════════════════════
# SIMPLE SCORING (no verification)
# ══════════════════════════════════════════════════════════════════════════════

def compute_simple_scores(answers: list[dict]) -> pd.DataFrame:
    rows = []
    for a in answers:
        sel = a.get("selected", "")
        raw_score = CHOICE_SCORE.get(sel, 0)
        rows.append({
            "ID":            a.get("id", ""),
            "Pillar":        a.get("pillar", ""),
            "Question":      a.get("question", "")[:120],
            "Selected":      sel,
            "Selected Text": a.get("selected_text", ""),
            "Raw Score":     raw_score,
            "Max Score":     MAX_SCORE_PER_QUESTION,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["Final Score"] = df["Raw Score"]  # no LLM multiplier in form-only mode
    return df


# ══════════════════════════════════════════════════════════════════════════════
# RESOLVE CURRENT USER
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_user() -> str | None:
    u = st.session_state.get("user")
    if u:
        return u
    try:
        params = get_query_params()
        if "user" in params and params["user"]:
            st.session_state["user"] = params["user"][0]
            return st.session_state["user"]
    except Exception:
        pass
    return None


# ── Session defaults ───────────────────────────────────────────────────────────
_DEFAULTS = {
    "answer_data":         None,
    "active_session_id":   None,
    "active_session_path": None,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    st.caption("Form-only mode: LLM and OCR disabled.")

# ── Main ──────────────────────────────────────────────────────────────────────
st.title("📝 MCQ Form (No LLM / No OCR)")
st.caption("Collect MCQ answers and save them to a session. Simple raw scoring only.")

current_user = _resolve_user()
if not current_user:
    st.warning("You are not logged in. Session history will not be persisted.")
    current_user = "anonymous"

st.header("Session Management")
col_new, col_pick = st.columns([1, 2])
with col_new:
    if st.button("➕ New Session", type="primary"):
        sid, spath = create_new_session(current_user)
        st.session_state.active_session_id   = sid
        st.session_state.active_session_path = str(spath)
        st.session_state.answer_data = None
        st.success(f"New session created: `{sid}`")
        st.rerun()

with col_pick:
    past_sessions = list_user_sessions(current_user)
    if past_sessions:
        labels = [f"{s['session_id']} · {s.get('company','—')}" for s in past_sessions]
        choice = st.selectbox("Load an existing session", options=["— select —"] + labels, key="sess_picker")
        if choice != "— select —":
            idx = labels.index(choice)
            picked = past_sessions[idx]
            if st.button("📂 Load"):
                st.session_state.active_session_id = picked["session_id"]
                st.session_state.active_session_path = str(get_session_path(current_user, picked["session_id"]))
                st.success(f"Session `{picked['session_id']}` loaded.")
                st.rerun()
    else:
        st.info("No previous sessions found.")

if not st.session_state.active_session_id:
    st.info("Create or load a session to begin.")
    st.stop()

active_sess_dir = Path(st.session_state.active_session_path)
active_sess_id  = st.session_state.active_session_id
sess_meta       = load_json(active_sess_dir / "metadata.json") or {}

st.info(f"Active session: `{active_sess_id}` · Company: `{sess_meta.get('company','—')}`")

# ── Step 1: Company & Answer Source ────────────────────────────────────────────
st.header("Step 1 — Company & Answer Source")
companies = sorted([p.name for p in DATA_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")])
if not companies:
    st.error("No company folders found in data/. Create a company folder with MCQ files or an esg_mcq.json in data/.")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    company_name = st.selectbox("Company", options=companies)
with col2:
    answer_mode = st.radio("Answer source", ["Load from file", "Use ESG question set"], index=1)

if sess_meta.get("company") != company_name:
    update_session_meta(active_sess_dir, {"company": company_name, "answer_mode": answer_mode})

answers: list[dict] = []
if st.session_state.get("answer_data"):
    answers = st.session_state.answer_data.get("answers", []) or []

if answer_mode == "Load from file":
    candidate_dir = Path(DATA_DIR) / company_name / "mcq_answers"
    answer_files = (sorted(candidate_dir.glob("*.json")) if candidate_dir.exists() else sorted((Path(DATA_DIR)/company_name).glob("*.json")))
    if not answer_files:
        st.warning("No MCQ answer files found for this company.")
    else:
        selected_file = st.selectbox("MCQ Answer File", options=answer_files, format_func=lambda p: p.name)
        if selected_file:
            data = load_json(selected_file)
            if not data:
                st.error("Could not load selected file.")
            else:
                data = data if isinstance(data, dict) else {"answers": []}
                data["source_file"] = selected_file.name
                st.session_state.answer_data = data
                answers = data.get("answers", [])
                st.success(f"Loaded {len(answers)} answers from {selected_file.name}")

elif answer_mode == "Use ESG question set":
    if not ESG_MCQ:
        st.error("ESG question set not found (data/esg_mcq.json).")
    else:
        st.markdown(f"Using ESG question set ({len(ESG_MCQ)} questions). Fill answers below.")
        with st.form("esg_form", clear_on_submit=False):
            esg_answers = []
            for q in ESG_MCQ:
                qid           = str(q.get("id") or q.get("ID") or q.get("qid") or f"q_{len(esg_answers)+1}")
                pillar        = q.get("pillar", q.get("Pillar", ""))
                question_text = q.get("question", q.get("text", ""))
                raw_choices   = q.get("choices") or q.get("options") or []
                opts = []
                if isinstance(raw_choices, dict):
                    for k, v in raw_choices.items():
                        opts.append((str(k).upper(), str(v)))
                elif isinstance(raw_choices, list):
                    for i, item in enumerate(raw_choices):
                        opts.append((["A","B","C","D","E"][i] if i < 5 else str(i+1), str(item)))
                else:
                    opts = [("A","A"),("B","B"),("C","C"),("D","D")]

                choice_labels   = [f"{l}: {t}" for l, t in opts]
                sel             = st.selectbox(f"{qid} — {pillar}\n{question_text}", options=choice_labels, key=f"esg_sel_{qid}")
                selected_letter = sel.split(":", 1)[0].strip()
                opt_map         = {l: t for l, t in opts}
                selected_text   = st.text_input(f"Selected text for {qid} (optional)", value=opt_map.get(selected_letter, ""), key=f"esg_text_{qid}")
                esg_answers.append({
                    "id": qid, "pillar": pillar, "question": question_text,
                    "selected": selected_letter, "selected_text": selected_text,
                })
            submitted = st.form_submit_button("Save answers to session")
        if submitted:
            answers = esg_answers
            st.session_state.answer_data = {
                "company":     company_name,
                "timestamp":   datetime.utcnow().isoformat() + "Z",
                "mode":        "esg_mcq_interactive",
                "source_file": "interactive_esg",
                "answers":     answers,
            }
            inputs_dir = active_sess_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            save_json(inputs_dir / "answers.json", st.session_state.answer_data)
            update_session_meta(active_sess_dir, {"status": "answers_saved"})
            st.success(f"Collected {len(answers)} answers — saved to session inputs/answers.json")

            # --- Immediately compute simple scores and create outputs so dashboard can see this submission ---
            try:
                df_local = compute_simple_scores(answers)
                total_raw = int(df_local["Raw Score"].sum()) if not df_local.empty else 0
                total_max = int(df_local["Max Score"].sum()) if not df_local.empty else 0
                pct = (total_raw / total_max * 100) if total_max > 0 else 0.0

                outputs_dir = active_sess_dir / "outputs"
                outputs_dir.mkdir(parents=True, exist_ok=True)

                # answers_saved.json (full payload)
                save_json(outputs_dir / "answers_saved.json", {
                    "company": company_name,
                    "session_id": active_sess_id,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "answers": answers,
                    "summary": {"total_raw": total_raw, "total_max": total_max, "pct": pct},
                })

                # verification.json (lightweight summary consumed by dashboard)
                save_json(outputs_dir / "verification.json", {
                    "session_id": active_sess_id,
                    "company": company_name,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "answers_count": len(answers),
                    "total_raw": total_raw,
                    "total_max": total_max,
                    # dashboard expects pct_verified, total_final_score etc.
                    "pct_verified": round(pct, 1),
                    "total_final_score": total_raw,
                })

                # raw scores CSV for convenience
                df_local.to_csv(outputs_dir / "scores_raw.csv", index=False)
                update_session_meta(active_sess_dir, {"status": "outputs_saved"})
            except Exception:
                # non-fatal: keep going, user still has inputs saved
                pass

# ── Step 2: Results & Download ─────────────────────────────────────────────────
st.header("Results (form-only)")

df = compute_simple_scores(answers)
if df.empty:
    st.warning("No answers to score.")
else:
    total_raw = int(df["Raw Score"].sum())
    total_max = int(df["Max Score"].sum())
    pct       = (total_raw / total_max * 100) if total_max > 0 else 0
    st.metric("Total Raw Score", f"{total_raw}/{total_max}")
    st.metric("Percentage (raw)", f"{pct:.1f}%")

    st.subheader("Per-question")
    st.dataframe(df, use_container_width=True)

    st.subheader("Pillar summary")
    pillar_summary = df.groupby("Pillar").agg(
        Questions=("ID","count"),
        Raw_Score=("Raw Score","sum"),
        Max_Score=("Max Score","sum"),
    ).reset_index()
    pillar_summary["Pct"] = (pillar_summary["Raw_Score"] / pillar_summary["Max_Score"] * 100).round(1)
    st.dataframe(pillar_summary, use_container_width=True)

    # Save outputs to session outputs/
    outputs_dir = active_sess_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    save_json(outputs_dir / "answers_saved.json", {
        "company": company_name,
        "session_id": active_sess_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "answers": answers,
        "summary": {"total_raw": total_raw, "total_max": total_max, "pct": pct},
    })
    df.to_csv(outputs_dir / "scores_raw.csv", index=False)

    st.subheader("Download")
    st.download_button(
        "📥 Download Answers JSON",
        data=json.dumps({
            "company": company_name,
            "session_id": active_sess_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "answers": answers,
        }, ensure_ascii=False, indent=2),
        file_name=f"{safe_name(company_name)}_{active_sess_id}_answers.json",
        mime="application/json",
    )
    st.download_button(
        "📥 Download Scores CSV",
        data=df.to_csv(index=False),
        file_name=f"{safe_name(company_name)}_{active_sess_id}_scores.csv",
        mime="text/csv",
    )

st.stop()

# insert new helper + UI for listing/viewing submissions before the "if not answers:" check
def list_user_submissions(username: str) -> list[dict]:
    result = []
    base = get_sessions_dir(username)
    if not base.exists():
        return result
    for s in sorted(base.iterdir(), reverse=True):
        if not s.is_dir():
            continue
        out_dir = s / "outputs"
        ver = out_dir / "verification.json"
        ans = out_dir / "answers_saved.json"
        item = {"session_id": s.name, "session_path": str(s)}
        if ver.exists():
            try:
                j = json.loads(ver.read_text(encoding="utf-8"))
                item.update({
                    "company": j.get("company", ""),
                    "timestamp": j.get("timestamp", ""),
                    "pct_verified": j.get("pct_verified", None),
                    "answers_count": j.get("answers_count", None),
                })
            except Exception:
                pass
        elif ans.exists():
            try:
                j = json.loads(ans.read_text(encoding="utf-8"))
                item.update({
                    "company": j.get("company", ""),
                    "timestamp": j.get("timestamp", ""),
                    "answers_count": len(j.get("answers", [])),
                    "pct_verified": (j.get("summary", {}).get("pct") if isinstance(j.get("summary", {}), dict) else None),
                })
            except Exception:
                pass
        result.append(item)
    return result

# place this UI block after the company/answer_source logic, before the existing "if not answers:" check
st.header("My Submissions")
subs = list_user_submissions(current_user)
if not subs:
    st.info("No submissions found for your account yet.")
else:
    df_subs = pd.DataFrame(subs)
    # Nice display: reorder columns if present
    cols = ["session_id", "company", "timestamp", "answers_count", "pct_verified"]
    present = [c for c in cols if c in df_subs.columns]
    st.dataframe(df_subs[present], use_container_width=True, hide_index=True)

    sel = st.selectbox("View submission", options=["— select —"] + [f"{r['session_id']} · {r.get('company','')}" for r in subs], key="view_sub_pick")
    if sel != "— select —":
        idx = [f"{r['session_id']} · {r.get('company','')}" for r in subs].index(sel)
        picked = subs[idx]
        if st.button("🔍 View submission details"):
            # load outputs/answers_saved.json if exists, else show verification.json summary
            out_path = Path(picked["session_path"]) / "outputs" / "answers_saved.json"
            ver_path = Path(picked["session_path"]) / "outputs" / "verification.json"
            if out_path.exists():
                payload = load_json(out_path)
                answers_view = payload.get("answers", [])
                df_view = compute_simple_scores(answers_view)
                st.subheader(f"Submission: {picked['session_id']} — {picked.get('company','')}")
                if df_view.empty:
                    st.info("No per-question answers to show.")
                else:
                    st.dataframe(df_view, use_container_width=True)
                    st.markdown("Summary:")
                    st.write(payload.get("summary", {}))
            elif ver_path.exists():
                payload = load_json(ver_path)
                st.subheader(f"Submission summary: {picked['session_id']} — {picked.get('company','')}")
                st.json(payload)
            else:
                st.error("No outputs found for that submission.")

if not answers:
    st.info("No answers available yet. Fill the form or load from file above.")
    st.stop()
