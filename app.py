"""Positioning Drift — Streamlit UI. One screen. Run: python -m streamlit run app.py

The product question is not "are you visible" but "is AI describing the company you are trying to
be". Everything on this page serves that one question; the evidence trail lives behind an expander.
"""
import html

import streamlit as st

import drift
import graph
from drift import OWNER_TEXT
from agents import onboarding
from providers import fixture, imported, live
from reports import list_runs, load_run, mode_label, save_run, to_json, to_markdown

st.set_page_config(page_title="Positioning Drift", page_icon="🎯", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 2.2rem; max-width: 1180px;}
.banner {border-radius: 8px; padding: .7rem 1rem; margin-bottom: 1.4rem; font-size: .9rem;
         background: #fff7e6; border: 1px solid #f0c36d; color: #5c3b00;}
.row {border-bottom: 1px solid #eaeef2; padding: .55rem 0;}
.zone {display:inline-block; padding:.08rem .55rem; border-radius:999px; font-size:.72rem; border:1px solid;}
.z-landed {background:#e6f4ea; border-color:#a8d5b5; color:#1e5b33;}
.z-lost {background:#fdecec; border-color:#f1b0b0; color:#8a1c1c;}
.z-unstated {background:#fff4e5; border-color:#f3c98b; color:#7a4b00;}
.z-imposed {background:#eef2ff; border-color:#c3cdfa; color:#2e3a8c;}
.z-unprioritised {background:#e4f5f8; border-color:#9fd0da; color:#0b5563;}
.z-contested {background:#fbe9f0; border-color:#f0aac4; color:#8a1c4b;}
.bar {height:15px; border-radius:3px;}
.attr {font-size:.93rem; color:#24292f; padding-top:.1rem;}
.muted {color:#57606a; font-size:.8rem;}
.quote {border-left:3px solid #8c959f; padding-left:.6rem; color:#24292f; font-style:italic; font-size:.88rem;}
</style>""", unsafe_allow_html=True)

SS = st.session_state
SS.setdefault("scenario", "A")
SS.setdefault("profile", None)
SS.setdefault("run", None)
SS.setdefault("run_requested", False)
SS.setdefault("notice", None)

ZONE_CLS = {"landed": "z-landed", "lost_claim": "z-lost", "unstated_intent": "z-unstated",
            "imposed": "z-imposed", "contested": "z-contested", "unprioritised": "z-unprioritised"}
ZONE_LABEL = {"landed": "landed", "lost_claim": "lost claim", "unstated_intent": "never stated",
              "imposed": "imposed", "contested": "contested", "unprioritised": "unprioritised"}
OWNER_TITLE = {"authority_gap": "Authority gap", "messaging_gap": "Messaging gap",
               "imposed_identity": "Imposed identity", "contested_identity": "Contested identity",
               "unprioritised_claim": "Unprioritised", "none": "Aligned"}


def esc(t):
    return html.escape(str(t))


def load_demo():
    SS.profile, SS.run, SS.notice = fixture.bundled_profile(SS.scenario), None, None


def request_run():
    SS.run_requested = True


def reset_all():
    SS.scenario = "A"
    load_demo()


def build_custom():
    """Arbitrary companies must never silently inherit the bundled company's replay data."""
    SS.profile = onboarding.profile_from_user_input(
        SS.get("c_name", ""), SS.get("c_site", ""), SS.get("c_text", ""),
        (SS.get("c_points", "") or "").splitlines())
    SS.run, SS.notice = None, None


def reopen():
    rid = SS.get("reopen_id")
    if rid:
        SS.run = load_run(rid)
        SS.profile = SS.run.profile


def replay_error(profile):
    try:
        fixture.FixtureProvider(SS.scenario).check_profile(profile)
    except fixture.ReplayUnavailable as e:
        return str(e)
    return None


# ---------------- header ----------------
st.title("Positioning Drift")
st.caption("How different is your brand in AI answers from the brand you are trying to be?")

run = SS.run
lines = [f"<b>{esc(mode_label(run) if run else 'SYNTHETIC DEMO — fixture replay; no live chatbot measurements; model judgment simulated.')}</b>",
         "Independent portfolio demo — not a Profound product or integration."]
if (_d := fixture.dev_delay()):
    lines.append(f"<b>DEV MODE — artificial {_d:g}s stall per answer. UI test only, not provider latency.</b>")
st.markdown(f'<div class="banner">{"<br>".join(lines)}</div>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader("Demo controls")
    st.radio("Synthetic scenario", ["A", "B"], key="scenario", on_change=load_demo,
             format_func=lambda s: f"Scenario {s}")
    st.button("Reset to original sample", on_click=reset_all, width="stretch")
    with st.expander("Analyse a different company"):
        st.text_input("Company name", key="c_name")
        st.text_input("Website", key="c_site")
        st.text_area("Positioning points (one per line)", key="c_points", height=80)
        st.text_area("Pasted facts (optional)", key="c_text", height=68)
        st.button("Build profile", key="build_custom", on_click=build_custom, width="stretch")
    ids = [p.stem for p in list_runs()]
    if ids:
        with st.expander("Reopen a completed run"):
            st.selectbox("Run id", ids, key="reopen_id")
            st.button("Reopen", key="reopen_btn", on_click=reopen, width="stretch")
    st.caption(f"Live API adapter: {live.status()}")

if SS.profile is None:
    load_demo()
p = SS.profile

# ---------------- setup / run ----------------
err = replay_error(p)
if run is None and err:
    st.warning(err)
    st.markdown("**Research plan**\n" + "\n".join(f"1. {x}" for x in onboarding.research_plan(p)))
    st.stop()

if run is None:
    prov = fixture.FixtureProvider(SS.scenario)
    attrs = prov.attributes()
    intended = [a for a in attrs if a.intended]
    st.markdown(f"#### {esc(p.name)} wants to be known for")
    cols = st.columns(len(intended) or 1)
    for c, a in zip(cols, intended):
        claim = drift.claim_strength(a)
        c.markdown(f"**{esc(a.label)}**<br><span class='muted'>intent {a.intended_weight:g} · "
                   f"stated on {int((claim or 0) * 100)}% of known pages</span>", unsafe_allow_html=True)
    st.write("")
    c1, c2 = st.columns([1, 4])
    c1.button("Measure drift", key="measure", type="primary", on_click=request_run, width="stretch")
    c2.caption(f"Asks {len(prov.named_probes())} questions that name the brand but never name an attribute, "
               f"plus 12 blind questions that never name the brand. Replayed from authored fixtures.")

if SS.run_requested:
    SS.run_requested = False  # consumed before executing: rerenders never restart a run
    prov = fixture.FixtureProvider(SS.scenario)
    new = graph.new_run(p, prov)
    with st.status("Running the LangGraph workflow…", expanded=True) as status:
        try:
            for node, new in graph.stream(new, prov):
                stage, agent = graph.STAGES[node]
                status.write(f"`{node}` · {stage} · {agent} — {new.log[-1] if new.log else ''}")
            save_run(new)
            SS.run = run = new
            status.update(label="Analysis complete", state="complete", expanded=False)
            st.rerun()  # drop the setup block; results own the screen from here
        except Exception as e:
            status.update(label="Run failed", state="error")
            st.error(f"{type(e).__name__}: {e}")
            st.stop()

if run is None or run.drift is None:
    st.stop()

# ---------------- the one screen ----------------
d = run.drift
st.write("")
m = st.columns([1.6, 1, 1, 1, 1])
m[0].metric("Positioning alignment", f"{d.alignment:g}%" if d.alignment is not None else "n/a",
            help="Weighted share of your intended attributes that AI actually echoes. Intended attributes only.")
m[1].metric("Landed", len(d.landed))
m[2].metric("Lost claims", len(d.lost_claims))
m[3].metric("Never stated", len(d.unstated_intent))
m[4].metric("Imposed", len(d.imposed))

st.caption(f"{d.n_named} named answers drive perception · {d.n_blind} blind answers give a separate "
           f"visibility score of {d.visibility:g}/100 · all synthetic" if d.visibility is not None
           else f"{d.n_named} named answers · all synthetic")
st.write("")

h = st.columns([2.4, 1.6, 1.6, 1.2])
h[1].markdown("<span class='muted'>What you claim</span>", unsafe_allow_html=True)
h[2].markdown("<span class='muted'>What AI says</span>", unsafe_allow_html=True)

ORDER = {"contested": 0, "lost_claim": 1, "unstated_intent": 2, "imposed": 3, "unprioritised": 4,
         "landed": 5}
for s in sorted(run.attribute_scores, key=lambda x: (ORDER[x.zone], -(x.echo_rate or 0))):
    c = st.columns([2.4, 1.6, 1.6, 1.2])
    c[0].markdown(f"<div class='attr'>{esc(s.label)}</div>"
                  + (f"<span class='muted'>intent {s.intended_weight:g}</span>" if s.intended_weight else
                     "<span class='muted'>not claimed by you</span>"), unsafe_allow_html=True)
    cw = int((s.claim_strength or 0) * 100)
    ew = int((s.echo_rate or 0) * 100)
    fill = {"landed": "#2da44e", "lost_claim": "#cf222e", "unstated_intent": "#bf8700",
            "imposed": "#4c5fd7", "contested": "#bf3989", "unprioritised": "#0f7b8a"}[s.zone]
    c[1].markdown(f"<div class='bar' style='width:{cw}%;background:#8c959f'></div>"
                  f"<span class='muted'>{cw}% of pages</span>", unsafe_allow_html=True)
    c[2].markdown(f"<div class='bar' style='width:{ew}%;background:{fill}'></div>"
                  f"<span class='muted'>{s.echoes}/{s.n} answers</span>", unsafe_allow_html=True)
    c[3].markdown(f"<span class='zone {ZONE_CLS[s.zone]}'>{ZONE_LABEL[s.zone]}</span>", unsafe_allow_html=True)

# ---------------- whose problem is it ----------------
st.write("")
st.markdown("#### Whose problem is each gap?")
gaps = [s for s in run.attribute_scores if s.zone in ("contested", "lost_claim", "unstated_intent", "imposed")]
gaps.sort(key=lambda s: (ORDER[s.zone], -((s.intended_weight or 0))))
for s in gaps[:4]:
    with st.container(border=True):
        st.markdown(f"**{esc(s.label)}** &nbsp; <span class='zone {ZONE_CLS[s.zone]}'>{OWNER_TITLE[s.owner]}</span>",
                    unsafe_allow_html=True)
        st.write(OWNER_TEXT[s.owner])
        cs = f"{int(s.claim_strength * 100)}% of your known pages state it" if s.claim_strength is not None else "no page data"
        st.caption(f"{cs} · AI echoed it in {s.echoes} of {s.n} named answers"
                   + (f" · {s.negative_echoes} negative" if s.negative_echoes else ""))
        if s.quotes:
            st.markdown(f"<div class='quote'>{esc(s.quotes[0])}</div>", unsafe_allow_html=True)
        if s.owner == "authority_gap":
            st.caption("Relevant capability: citation analysis / Answer Engine Insights — "
                       "https://www.tryprofound.com/features/answer-engine-insights")
        elif s.owner == "messaging_gap":
            st.caption("Not an AI problem: your own copy does not state this clearly enough to be repeated.")
        elif s.owner in ("imposed_identity", "contested_identity"):
            st.caption("Relevant capability: sentiment/theme analysis — "
                       "https://www.tryprofound.com/features/answer-engine-insights")

# ---------------- evidence ----------------
with st.expander("How do you know? Evidence, limitations and the full run"):
    st.markdown("**Limitations**")
    for l in d.limitations:
        st.markdown(f"- {l}")
    st.markdown("**Named questions asked** (never contain an attribute name)")
    ans = {a.probe_id: a for a in run.answers}
    for pr in [x for x in run.probes if x.kind == "named"]:
        with st.container(border=True):
            st.markdown(f"`{pr.id}` **{esc(pr.text)}**")
            st.caption(esc(ans[pr.id].text) if pr.id in ans else "no answer")
    st.markdown("**Workflow log**")
    for l in run.log:
        st.markdown(f"- {esc(l)}")

c1, c2 = st.columns(2)
c1.download_button("Download JSON", to_json(run), f"drift_{run.id}.json", "application/json", width="stretch")
c2.download_button("Download Markdown", to_markdown(run), f"drift_{run.id}.md", "text/markdown", width="stretch")
