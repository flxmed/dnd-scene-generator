import streamlit as st
from google import genai
import json
import re
import os

st.set_page_config(page_title="D&D Scene Generator", page_icon="⚔️")


if "api_key" not in st.session_state:
    st.session_state.api_key = ""

api_key = st.text_input(
    "Enter your Gemini API Key",
    type="password",
    value=st.session_state.api_key
)

if api_key:
    st.session_state.api_key = api_key

if not st.session_state.api_key:
    st.warning("API key required to continue")
    st.stop()

client = genai.Client(api_key=st.session_state.api_key)

MODEL = "gemini-3.5-flash"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600&family=Crimson+Text:ital,wght@0,400;1,400&display=swap');
.scene-output { font-family: 'Crimson Text', Georgia, serif; font-size: 18px; line-height: 1.9; }
h1 { font-family: 'Cinzel', serif !important; }
div[data-baseweb="select"] input { caret-color: transparent !important; }
</style>
""", unsafe_allow_html=True)

st.title("⚔️ D&D Scene Generator")

class WorldState:
    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.scene_count: int = 0

    def update_from_scene(self, updates: dict):
        if not isinstance(updates, dict):
            return

        for entity, data in updates.items():
            if not isinstance(entity, str) or not isinstance(data, dict):
                continue

            key = re.sub(r"[^a-zA-Zа-яА-Я0-9 ]", "", entity.lower()).strip()
            new_state = str(data.get("state", "")).strip()
            new_trend = str(data.get("trend", "")).strip()
            if not new_state:
                continue

            if key not in self.entities:
                self.entities[key] = {
                    "state": new_state,
                    "trend": new_trend,
                    "confidence": 1.0,
                    "last_update": self.scene_count
                }
                continue

            existing = self.entities[key]

            age = self.scene_count - existing.get("last_update", 0)
            decay = max(0.5, 0.85 ** age)
            confidence = existing["confidence"] * decay

            if new_state != existing["state"]:
                stability = confidence / (1 + age * 0.2)

                if stability < 1.2:
                    existing["state"] = new_state
                    existing["confidence"] = 1.0
                    existing["last_update"] = self.scene_count
                    existing["trend"] = new_trend
                else:
                    existing["confidence"] = min(existing["confidence"] + 0.3, 5.0)
            else:
                existing["trend"] = new_trend or existing.get("trend", "unknown")
                existing["confidence"] = min(confidence + 0.2, 5.0)
                existing["last_update"] = self.scene_count

            self.entities[key] = existing

    def to_prompt_block(self) -> str:
        if not self.entities:
            return ""

        lines = []
        for entity, data in self.entities.items():
            state = data.get("state", "unknown")
            trend = data.get("trend", "unknown")
            line = f"  {entity}.state = {state}, trend = {trend}"
            lines.append(line)

        return "WORLD_STATE:\n" + "\n".join(lines)

    def summary(self):
        return [(e, d.get("state", ""), d.get("trend", "")) for e, d in self.entities.items()]


def resolve_conflicts(pacing: str, intensity: str, focus: str) -> dict:
    r = {}

    if pacing == "Швидко":
        r["para_len"] = "2–3 sentences each"
        r["structure_note"] = "¶1 and ¶2 compress — keep ¶3 anomaly intact"
    elif pacing == "Повільно":
        r["para_len"] = "4–6 sentences each"
        r["structure_note"] = "Unhurried — let details accumulate"
    else:
        r["para_len"] = "mixed length"
        r["structure_note"] = "Standard pacing"

    if intensity == "Екстремально":
        r["verbosity"] = "sensory overload — pile physical details"
    elif intensity == "Тихо":
        r["verbosity"] = "sparse — minimal detail"
    else:
        r["verbosity"] = "balanced"

    focus_map = {
        "Середовище": "terrain, architecture, weather dominate",
        "Істоти": "creature presence dominates",
        "Таємниця": "clues dominate",
        "Виживання": "threat dominates",
        "Насилля": "aftermath dominates",
        "Лор": "ruins and symbols dominate",
        "Емоція": "emotional undercurrent via physical detail",
    }

    r["focus"] = focus_map.get(focus, "")
    return r


TONE_PROFILES = {
    "Похмуре виживання": "exhaustion, cold, hunger — environment is the enemy",
    "Героїчне фентезі": "scale, grandeur, wonder",
    "Темний жах": "reality distortion, corrupted details",
    "Таємниця / Розслідування": "clues and inconsistencies",
    "Диво / Міф": "awe and mythic calm",
    "Затишний відпочинок": "warmth and safety",
    "Напружена дія": "urgency and movement",
    "Політика / Соціальна напруга": "tension and power",
}

INTENSITY_MAP = {
    "Тихо": "danger_density=none",
    "Помірно": "danger_density=low",
    "Сильно": "danger_density=high",
    "Екстремально": "danger_density=extreme",
}

PACING_MAP = {
    "Повільно": "slow burn",
    "Збалансовано": "balanced",
    "Швидко": "fast",
}


EXTRACTION_PROMPT = """Extract named entities from this D&D scene description.
Return ONLY valid JSON.

Format:
{
  "entity": {"state": "...", "trend": "..."}
}

If none: return {}.

SCENE:
"""


def _normalize_entities(data: dict) -> dict:
    cleaned = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, dict):
            cleaned[k] = {
                "state": str(v.get("state", "")).strip(),
                "trend": str(v.get("trend", "")).strip()
            }
    return cleaned


def extract_entities(scene: str) -> dict:
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=EXTRACTION_PROMPT + scene,
        )

        raw = (resp.text or "").strip()

        try:
            return _normalize_entities(json.loads(raw))
        except:
            pass

        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return {}

        try:
            return _normalize_entities(json.loads(raw[start:end+1]))
        except:
            return {}

    except Exception as e:
        st.warning(f"Entity extraction failed: {e}")
        return {}


def build_prompt(location: str, tone: str, intensity: str, pacing: str,
                 focus: str, language: str, world: WorldState) -> str:

    r = resolve_conflicts(pacing, intensity, focus)
    world_block = world.to_prompt_block()

    config = f"""<scene_config>
tone: {tone} — {TONE_PROFILES[tone]}
intensity: {intensity} — {INTENSITY_MAP[intensity]}
pacing: {pacing} — {PACING_MAP[pacing]}
focus: {r['focus']}
paragraph_length: {r['para_len']}
verbosity: {r['verbosity']}
language: {language}
</scene_config>"""

    structure = f"""<output_structure>
¶1 — First contact.
¶2 — Space opens visually.
¶3 — Physical contradiction.
note: {r['structure_note']}
</output_structure>"""

    voice = """<voice>
DM talking to players.
Physical sensations over abstract description.
Max 2 sensory signals per paragraph.
</voice>"""

    objective = """<objective>
Goal: produce a physically grounded D&D scene spoken by a dungeon master.

Constraints hierarchy:
1. physical realism > style
2. sensory clarity > prose
3. world consistency > novelty

Rules:
- exactly 3 paragraphs
- every paragraph must contain a physical cause → sensory effect chain
- no abstract narration
- no symbolic interpretation
- no poetic omniscient narration
- world state is probabilistic but should remain consistent unless physically changed
- do not escalate violence beyond the user input.
- keep violence implied through consequences unless explicitly requested.
</objective>"""

    return f"""{config}

{structure}

{voice}

{objective}

{world_block}

<input>{location}</input>
"""


def generate_scene(location, tone, intensity, pacing, focus, language, world):
    prompt = build_prompt(location, tone, intensity, pacing, focus, language, world)
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    return resp.text or ""


if "world" not in st.session_state:
    st.session_state.world = WorldState()
if "scenes" not in st.session_state:
    st.session_state.scenes = []
if "current_scene" not in st.session_state:
    st.session_state.current_scene = ""


location = st.text_area("Ідея локації")

col1, col2 = st.columns(2)
with col1:
    tone = st.selectbox("Тон", list(TONE_PROFILES.keys()))
with col2:
    language = st.selectbox("Мова", ["Українська", "English", "Русский"])

col3, col4, col5 = st.columns(3)
with col3:
    intensity = st.selectbox("Інтенсивність", list(INTENSITY_MAP.keys()))
with col4:
    pacing = st.selectbox("Темп", list(PACING_MAP.keys()))
with col5:
    focus = st.selectbox(
        "Фокус",
        ["Середовище","Істоти","Таємниця","Виживання","Насилля","Лор","Емоція"]
    )

col_gen, col_regen = st.columns(2)
run = False

with col_gen:
    if st.button("Згенерувати"):
        run = bool(location.strip())

with col_regen:
    if st.button("Регенерувати"):
        run = bool(st.session_state.current_scene and location.strip())


if run:
    with st.spinner("Generating..."):
        scene = generate_scene(location, tone, intensity, pacing, focus, language, st.session_state.world)

        st.session_state.current_scene = scene
        st.session_state.scenes.append({"input": location, "scene": scene})

        st.session_state.world.scene_count += 1

        entity_json = extract_entities(scene)
        st.session_state.world.update_from_scene(entity_json)


if st.session_state.current_scene:
    st.markdown(st.session_state.current_scene)
