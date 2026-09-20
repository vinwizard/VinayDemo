"""Visibility Explorer — Streamlit UI. Run: python -m streamlit run app.py"""
import html

import streamlit as st

import graph
from agents import onboarding
from providers import fixture, imported, live
from reports import from_json, list_runs, load_run, mode_label, save_run, to_json, to_markdown

st.set_page_config(page_title="Visibility Explorer", page_icon="🔎", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1400px;}
.banner {border-radius: 8px; padding: .7rem 1rem; margin-bottom: 1rem; font-size: .92rem;
         background: #fff7e6; border: 1px solid #f0c36d; color: #5c3b00;}
.banner b {letter-spacing: .02em;}
.badge {display: inline-block; padding: .05rem .5rem; border-radius: 999px; font-size: .75rem;
        margin-right: .3rem; border: 1px solid #d0d7de; background: #f6f8fa; color: #24292f;}
.b-sourced {background: #e6f4ea; border-color: #a8d5b5; color: #1e5b33;}
.b-uncertain, .b-illustrative {background: #fff4e5; border-color: #f3c98b; color: #7a4b00;}
.b-user_provided {background: #eef2ff; border-color: #c3cdfa; color: #2e3a8c;}
.b-gap {background: #fdecec; border-color: #f1b0b0; color: #8a1c1c;}
.b-mixed {background: #fff4e5; border-color: #f3c98b; color: #7a4b00;}
.b-presence {background: #e6f4ea; border-color: #a8d5b5; color: #1e5b33;}
.stage {padding: .55rem .6rem; border-radius: 8px; border: 1px solid #d0d7de; font-size: .85rem; min-height: 4.2rem;}
.stage.done {background: #e6f4ea; border-color: #a8d5b5;}
.stage small {color: #57606a;}
.quote {border-left: 3px solid #8c959f; padding-left: .6rem; color: #24292f; font-style: italic;}
.muted {color: #57606a; font-size: .85rem;}
@media (prefers-color-scheme: dark) {
  .banner {background: #3a2a05; color: #ffe2a8; border-color: #7a5a14;}
  .stage.done {background: #10301c;}
  .quote, .badge {color: inherit;}
  .muted, .stage small {color: #9da7b1;}
}
</style>""", unsafe_allow_html=True)

SS = st.session_state
SS.setdefault("screen", "1 · Company setup")
SS.setdefault("scenario", "A")
SS.setdefault("profile", None)
SS.setdefault("run", None)
SS.setdefault("run_requested", False)
SS.setdefault("use_snapshot", True)
SS.setdefault("notice", None)
SCREENS = ["1 · Company setup", "2 · Investigation", "3 · Gap report"]
STATUS_BADGE = {"candidate gap": "b-gap", "mixed": "b-mixed", "observed presence": "b-presence"}


def badge(text, cls=""):
    return f'<span class="badge {cls}">{html.escape(str(text))}</span>'


def snapshot():
    snaps = imported.list_snapshots()
    return imported.load_snapshot(snaps[-1]) if snaps else None


# ---------- actions (callbacks run once per click, never on rerender) ----------
def load_demo():
    p = fixture.bundled_profile(SS.scenario)
    snap = snapshot()
    if SS.use_snapshot and snap:
        p = imported.apply_snapshot(p, snap)
    SS.profile, SS.run, SS.notice = p, None, None


def reset_all():
    SS.scenario, SS.use_snapshot, SS.screen = "A", True, SCREENS[0]
    load_demo()


def build_custom():
    if not SS.c_name.strip():
        SS.notice = "Enter a company name."
        return
    SS.profile = onboarding.profile_from_user_input(SS.c_name, SS.c_site, SS.c_text, SS.c_points.splitlines())
    SS.run, SS.notice = None, None


def save_edits():
    p = SS.profile
    for pp in p.positioning_points:
        p = onboarding.edit_point(p, pp.id, SS[f"edit_{pp.id}"])
    SS.profile, SS.run = p, None


def approve():
    SS.profile = SS.profile.model_copy(update={"approved": True})
    SS.screen = SCREENS[1]


def change_scenario():
    SS.run = None
    if SS.profile is not None and replay_error(SS.profile) is None:
        approved = SS.profile.approved
        load_demo()
        SS.profile.approved = approved


def toggle_snapshot():
    if SS.profile is None or SS.profile.name == "Notion":
        change_scenario()


def request_run():
    SS.run, SS.run_requested, SS.screen = None, True, SCREENS[1]


def reopen():
    if SS.get("reopen_id"):
        SS.run = load_run(SS.reopen_id)
        SS.profile, SS.scenario, SS.screen = SS.run.profile, SS.run.scenario or SS.scenario, SCREENS[2]


def import_run():
    f = SS.get("import_file")
    if f is None:
        return
    try:
        SS.run = from_json(f.getvalue().decode())
        SS.profile, SS.screen, SS.notice = SS.run.profile, SCREENS[2], None
    except Exception as e:  # show, don't crash
        SS.notice = f"Import rejected: {e}"


def replay_error(profile):
    try:
        fixture.FixtureProvider(SS.scenario).check_profile(profile)
        return None
    except fixture.ReplayUnavailable as e:
        return str(e)


# ---------- header ----------
st.title("Visibility Explorer")
st.caption("Find the buyer questions where your brand is missing.")
run = SS.run
lines = [f"<b>{html.escape(mode_label(run) if run else 'SYNTHETIC DEMO — fixture replay; no live chatbot measurements; model judgment simulated.')}</b>"]
if SS.profile is not None:
    kinds = sorted({e.source_type for e in SS.profile.evidence})
    lines.append("Company profile evidence: " + (", ".join(kinds) or "none")
                 + (" (Claude Code research snapshot; not cross-model chatbot visibility)" if "web_research_snapshot" in kinds else ""))
lines.append("Independent portfolio demo — not a Profound product or integration.")
if (_d := fixture.dev_delay()):
    lines.append(f"<b>DEV MODE — artificial {_d:g}s stall per answer ({fixture.DEV_DELAY_ENV}). "
                 "This is a local UI test, NOT provider latency. No provider is called. Do not screenshot for the demo.</b>")
st.markdown(f'<div class="banner">{"<br>".join(lines)}</div>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader("Demo controls")
    st.radio("Synthetic scenario", ["A", "B"], key="scenario", on_change=change_scenario,
             format_func=lambda k: fixture.FixtureProvider(k).title)
    st.checkbox("Use sourced research snapshot for profile evidence", key="use_snapshot", on_change=toggle_snapshot,
                disabled=snapshot() is None)
    st.button("Reset to original sample", on_click=reset_all, key="reset", width="stretch")
    st.divider()
    st.subheader("Completed runs")
    runs = list_runs()
    if runs:
        st.selectbox("Saved locally in data/runs/", [p.stem for p in runs], key="reopen_id")
        st.button("Reopen run", on_click=reopen, key="reopen_btn", width="stretch")
    else:
        st.caption("None yet.")
    st.file_uploader("Import run JSON", type="json", key="import_file", on_change=import_run)
    st.divider()
    st.caption(f"Live API adapter: {live.status()}")

if SS.notice:
    st.error(SS.notice)
screen = st.radio("Screen", SCREENS, key="screen", horizontal=True, label_visibility="collapsed")


# ---------- screen 1 ----------
def screen_setup():
    c1, c2 = st.columns([1, 2])
    c1.button("Load Notion demo", type="primary", on_click=load_demo, key="load_demo", width="stretch")
    with c2.expander("Or investigate another company (paste facts; URL fetching is disabled)"):
        st.text_input("Company name", key="c_name")
        st.text_input("Website", key="c_site", placeholder="example.com")
        st.text_area("Pasted company text (treated as untrusted data)", key="c_text", height=100)
        st.text_area("Positioning points, one per line (max 8)", key="c_points", height=100)
        st.button("Build profile from my facts", on_click=build_custom, key="build_custom")
    p = SS.profile
    if p is None:
        st.info("Load the Notion demo to walk through the full workflow with synthetic answers.")
        return
    st.subheader(f"{p.name} · {p.domain}")
    for w in p.warnings:
        st.caption(f"⚠️ {w}")
    a, b, c = st.columns(3)
    a.markdown("**Aliases**<br>" + " ".join(badge(x) for x in p.aliases) +
               "<br><br>**Owned domains**<br>" + " ".join(badge(x) for x in p.all_domains()), unsafe_allow_html=True)
    b.markdown("**Customer types**<br>" + "<br>".join(html.escape(x) for x in p.customer_types or ["—"]), unsafe_allow_html=True)
    c.markdown("**Capabilities / use cases**<br>" + "<br>".join(html.escape(x) for x in (p.capabilities + p.use_cases) or ["—"]),
               unsafe_allow_html=True)

    st.markdown("#### Positioning points")
    evidence = {e.id: e for e in p.evidence}
    prov = fixture.FixtureProvider(SS.scenario)
    err = replay_error(p)
    topics = prov.data["topics"] if err is None else []
    for pp in p.positioning_points:
        tested = [t["label"] for t in topics if pp.id in t["positioning_point_ids"]]
        st.markdown(f"{badge(pp.support, 'b-' + pp.support)} **{pp.id}** — {html.escape(pp.text)} "
                    f"<span class='muted'>→ {html.escape(', '.join(tested) or 'not tested')}</span>", unsafe_allow_html=True)
        for eid in pp.evidence_ids:
            e = evidence.get(eid)
            if e:
                src = f"<a href='{html.escape(e.url)}'>{html.escape(e.url)}</a>" if e.url else "no URL"
                st.markdown(f"<div class='quote'>{html.escape(e.excerpt)}</div>"
                            f"<span class='muted'>{badge(e.source_type, 'b-' + e.source_type)}{src}"
                            f"{' · retrieved ' + e.retrieved_at[:10] if e.retrieved_at else ''}</span>", unsafe_allow_html=True)
    with st.expander("Edit positioning (structural edit — invalidates bundled replay data)"):
        for pp in p.positioning_points:
            st.text_input(pp.id, value=pp.text, key=f"edit_{pp.id}")
        st.button("Save edits", on_click=save_edits, key="save_edits")

    st.markdown("#### Buyer topics")
    if err:
        st.warning(err)
        st.markdown("**Research plan**\n" + "\n".join(f"1. {s}" for s in onboarding.research_plan(p)))
        return
    sourced = all(pp.support == "sourced" for pp in p.positioning_points if any(pp.id in t["positioning_point_ids"] for t in topics))
    if not sourced:
        st.caption("Topic labels are illustrative until the company profile is sourced.")
    cols = st.columns(len(topics))
    for col, t in zip(cols, topics):
        with col.container(border=True):
            st.markdown(f"**{t['label']}**<br>{badge('fit: ' + t['fit'])}", unsafe_allow_html=True)
            st.caption(t["buyer_need"])
            st.caption("Positioning: " + ", ".join(t["positioning_point_ids"]))
    st.checkbox("I reviewed this profile and its evidence", key="reviewed")
    st.button("Explore visibility →", type="primary", disabled=not SS.get("reviewed"), on_click=approve, key="explore")


# ---------- screen 2 ----------
def stage_row(done_nodes):
    stages = [("Onboarding", "Agent 1 · Onboarding", SS.profile is not None and SS.profile.approved),
              ("Topic planning", "Agent 2 · AnA", "validate_and_freeze" in done_nodes),
              ("Baseline", "Orchestrator replay", "execute_or_replay" in done_nodes),
              ("Gap evaluation", "Agent 3 · Evaluation", "evaluate" in done_nodes),
              ("Follow-up", "Agent 2 · AnA (simulated policy)", "choose_followup" in done_nodes),
              ("Report", "Agent 3 · Evaluation", "build_gap_report" in done_nodes)]
    for col, (name, who, done) in zip(st.columns(6), stages):
        col.markdown(f"<div class='stage {'done' if done else ''}'>{'✅' if done else '○'} <b>{name}</b><br><small>{who}</small></div>",
                     unsafe_allow_html=True)


def screen_investigation():
    p = SS.profile
    if p is None:
        st.info("Load a company on the setup screen first.")
        return
    run = SS.run
    done = set(graph.STAGES) if run and run.status == "complete" else set()
    err = replay_error(p)
    if SS.run_requested and err is None and p.approved:
        SS.run_requested = False  # consume before executing: rerenders never restart a run
        prov = fixture.FixtureProvider(SS.scenario)
        new = graph.new_run(p, prov)
        with st.status("Running demo replay through the LangGraph workflow…", expanded=True) as status:
            try:
                for node, new in graph.stream(new, prov):
                    stage, agent = graph.STAGES[node]
                    status.write(f"✅ `{node}` · {stage} · {agent} — {new.log[-1] if new.log else ''}")
                    done.add(node)
                save_run(new)
                SS.run = run = new
                status.update(label="Demo replay complete", state="complete", expanded=False)
            except Exception as e:
                status.update(label="Run failed", state="error")
                st.error(f"{type(e).__name__}: {e}")
                return
    SS.run_requested = False
    stage_row(done)
    st.write("")
    if err:
        st.warning(err)
        st.markdown("**Research plan**\n" + "\n".join(f"1. {s}" for s in onboarding.research_plan(p)))
        return
    if not p.approved:
        st.info("Review and approve the profile on the setup screen first.")
        return
    c1, c2 = st.columns([1, 3])
    c1.button("Run demo replay", type="primary", on_click=request_run, key="run_replay", width="stretch")
    _delay = fixture.dev_delay()
    c2.caption("Replays authored fixture answers through real graph transitions. No provider is called; "
               + (f"an artificial {_delay:g}s/answer dev stall is ACTIVE ({fixture.DEV_DELAY_ENV}) — UI test only, "
                  "not provider latency; no token cost or live status is simulated."
                  if _delay else "no latency, token cost or live status is simulated."))
    if run is None:
        return
    base = sum(pr.phase == "baseline" for pr in run.probes)
    fu = len(run.probes) - base
    ok = sum(a.status == "ok" for a in run.answers)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Queries completed", f"{ok}/{len(run.probes)}")
    m2.metric("Baseline (frozen)", base)
    m3.metric("Exploratory follow-ups", fu)
    m4.metric("Status", run.status)
    st.markdown("#### AnA decision log")
    for d in run.decisions:
        st.markdown(f"{badge(d.policy)} **Selected:** {', '.join(d.selected_topics) or 'stop'}", unsafe_allow_html=True)
        for part in d.rationale.split(" | "):
            st.markdown(f"- {part}")
        for pr in d.new_probes:
            st.markdown(f"  - `{pr.id}` {pr.text} <span class='muted'>(from {', '.join(pr.parent_probe_ids)})</span>",
                        unsafe_allow_html=True)
    with st.expander("Orchestrator log"):
        st.code("\n".join(run.log))
    st.button("View gap report →", key="to_report", on_click=lambda: SS.update(screen=SCREENS[2]))


# ---------- screen 3 ----------
def question_detail(run, probe):
    a = next((x for x in run.answers if x.probe_id == probe.id), None)
    e = next((x for x in run.evaluations if x.probe_id == probe.id), None)
    label = f"{probe.id} · {probe.text}"
    strength = "failed" if e is None or e.strength is None else f"strength {e.strength}"
    with st.expander(f"{label}  —  {strength}"):
        st.caption(f"Purpose: {probe.purpose}" + (f" · motivated by {', '.join(probe.parent_probe_ids)}" if probe.parent_probe_ids else ""))
        if a is None:
            st.error("No answer recorded.")
            return
        st.markdown(f"{badge('provenance: ' + a.provenance)}{badge('provider: ' + (a.provider or '—'))}"
                    f"{badge('status: ' + a.status)}", unsafe_allow_html=True)
        st.markdown(f"<div class='quote'>{html.escape(a.text) or '(no answer text)'}</div>", unsafe_allow_html=True)
        if a.citations:
            st.markdown("Citations: " + " · ".join(html.escape(c) for c in a.citations), unsafe_allow_html=True)
        if e:
            (st.success if e.valid else st.error)(e.explanation)
            flags = {"mentioned": e.mentioned, "recommended": e.recommended, "negative": e.negative_mention,
                     "owned citation": e.owned_citation}
            st.markdown(" ".join(badge(f"{k}: {'yes' if v else 'no'}") for k, v in flags.items()), unsafe_allow_html=True)
            for q in e.evidence_quotes:
                st.markdown(f"Evidence quote: “{html.escape(q)}”")
            for w in e.warnings:
                st.warning(w)
            st.caption(f"Evaluator: {e.evaluator}")


def topic_table(run, phase):
    topics = {t.id: t for t in run.topics}
    rows = [{"Topic": topics[te.topic_id].label, "Fit": topics[te.topic_id].fit,
             "Recommended": f"{te.recommendations}/{te.n}",
             "Simulated visibility score" if run.mode == "demo_replay" else "Visibility score": te.visibility_score,
             "Owned citations": f"{te.owned_citations}/{te.n}", "Excluded": te.excluded, "Status": te.status,
             "Heuristic investigation priority": te.gap_priority}
            for te in run.topic_evaluations if te.phase == phase]
    st.dataframe(rows, hide_index=True, width="stretch")


def screen_report():
    run = SS.run
    if run is None or run.status != "complete":
        st.info("No completed run yet. Run the demo replay, or reopen a saved run from the sidebar.")
        return
    st.markdown(f"Run `{run.id}` · scenario {run.scenario} · baseline `{run.baseline_hash[:12]}` · {run.created_at}")
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("Download JSON", to_json(run), f"visibility-{run.id}.json", "application/json", key="dl_json",
                       width="stretch")
    d2.download_button("Download Markdown report", to_markdown(run), f"visibility-{run.id}.md", "text/markdown",
                       key="dl_md", width="stretch")
    d3.button("Replay again", on_click=request_run, key="replay_again", width="stretch",
              disabled=replay_error(run.profile) is not None)
    d4.button("Reset to original sample", on_click=reset_all, key="reset_main", width="stretch")

    t_base, t_help, t_fu, t_pos = st.tabs(["Baseline results", "Where Profound could help", "Exploratory follow-ups",
                                           "Positioning coverage"])
    topics = {t.id: t for t in run.topics}
    with t_base:
        st.caption("Scores are simulated from synthetic fixture answers. Every topic is a small sample (3 questions)."
                   if run.mode == "demo_replay" else "Every topic is a small sample.")
        topic_table(run, "baseline")
        for te in [x for x in run.topic_evaluations if x.phase == "baseline"]:
            t = topics[te.topic_id]
            with st.container(border=True):
                st.markdown(f"### {t.label} {badge(te.status, STATUS_BADGE.get(te.status, ''))}{badge('fit: ' + t.fit)}",
                            unsafe_allow_html=True)
                st.caption(f"Buyer need: {t.buyer_need} · fit evidence: {', '.join(t.fit_evidence_ids) or 'none'}")
                c = st.columns(5)
                c[0].metric("Recommended", f"{te.recommendations}/{te.n}")
                c[1].metric("Mentioned", f"{te.mentions}/{te.n}")
                c[2].metric("Visibility", "null" if te.visibility_score is None else f"{te.visibility_score:g}")
                c[3].metric("Competitor answers", f"{te.competitor_answers}/{te.n}")
                c[4].metric("Priority (heuristic)", "—" if te.gap_priority is None else f"{te.gap_priority:g}")
                if te.top_competitors:
                    st.caption("Competitors recommended: " + ", ".join(te.top_competitors))
                if te.excluded_reasons:
                    st.caption("Excluded: " + "; ".join(te.excluded_reasons))
                st.caption("Limitations: " + " ".join(te.limitations))
                nxt = next((f for f in run.findings if f.topic_id == t.id), None)
                st.markdown(f"**Suggested next action:** {nxt.suggested_action if nxt else 'None needed — keep monitoring with a wider fixed prompt set.'}")
                for pr in [p for p in run.probes if p.topic_id == t.id and p.phase == "baseline"]:
                    question_detail(run, pr)
    with t_help:
        st.caption("Possible fit between observed issues and Profound capabilities — an explanation, not a Profound API call "
                   "and not a promise of placement. Ranked by heuristic investigation priority (not revenue potential).")
        for f in run.findings:
            with st.container(border=True):
                st.markdown(f"**{topics[f.topic_id].label}** {badge(f.provenance)}"
                            + (badge(f'priority {f.gap_priority:g}') if f.gap_priority is not None else ""),
                            unsafe_allow_html=True)
                st.markdown(f"**Observation:** {f.observation}  \n**Interpretation:** {f.interpretation}")
                if f.profound_capability:
                    st.markdown(f"**Capability:** [{f.profound_capability}]({f.capability_url})  \n"
                                f"**Suggested action:** {f.suggested_action}")
                else:
                    st.markdown(f"**Capability:** insufficient evidence — none mapped  \n**Next:** {f.suggested_action}")
                st.caption(f"Evidence: {', '.join(f.evidence_ids)} · fit evidence: {', '.join(f.fit_evidence_ids) or 'none'}")
                with st.expander("Supporting evidence"):
                    for pid in f.evidence_ids:
                        e = next((x for x in run.evaluations if x.probe_id == pid), None)
                        pr = next((x for x in run.probes if x.id == pid), None)
                        if e and pr:
                            quotes = " ".join(f"“{q}”" for q in e.evidence_quotes)
                            st.markdown(f"**{pid}** {html.escape(pr.text)}  \n{html.escape(e.explanation)} {html.escape(quotes)}")
                if f.exploratory_note:
                    st.caption(f.exploratory_note)
                st.caption("Limitations: " + " ".join(f.limitations))
    with t_fu:
        st.caption("Exploratory observations are never merged into baseline scores. Two questions per topic is below the "
                   "evidence threshold, so no status or priority is assigned.")
        for d in run.decisions:
            st.markdown(f"**AnA decision** ({d.policy}): {d.rationale}")
        if any(te.phase == "followup" for te in run.topic_evaluations):
            topic_table(run, "followup")
        for pr in [p for p in run.probes if p.phase == "followup"]:
            question_detail(run, pr)
    with t_pos:
        status = {te.topic_id: te.status for te in run.topic_evaluations if te.phase == "baseline"}
        for pp in run.profile.positioning_points:
            tested = [t for t in run.topics if pp.id in t.positioning_point_ids]
            res = ", ".join(f"{t.label}: {status.get(t.id, '—')}" for t in tested) or "not tested"
            st.markdown(f"{badge(pp.support, 'b-' + pp.support)} **{pp.id}** {html.escape(pp.text)} → {html.escape(res)}",
                        unsafe_allow_html=True)


{SCREENS[0]: screen_setup, SCREENS[1]: screen_investigation, SCREENS[2]: screen_report}[screen]()
