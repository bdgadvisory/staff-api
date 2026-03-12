import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from anthropic import Anthropic

from search import serper_search, Source

router = APIRouter(prefix="/scribe", tags=["scribe"])


def _get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise HTTPException(status_code=500, detail=f"Missing env var: {name}")
    return v


def _anthropic_client() -> Anthropic:
    return Anthropic(api_key=_get_env("ANTHROPIC_API_KEY"))


def _model(name: str, default: str) -> str:
    return os.getenv(name, default)


DEFAULT_SONNET = "claude-sonnet-4-6"


class ScribeLinkedInRequest(BaseModel):
    topic: str = Field(..., description="What the post is about")
    angle: Optional[str] = Field(None, description="Optional framing/angle")
    audience: Optional[str] = Field(None, description="Optional audience hint")
    num_sources: int = Field(5, ge=3, le=10, description="How many web sources to use")
    voice: bool = Field(True, description="Run Voice pass (style/consistency) after Quill")


class ResearchPacket(BaseModel):
    query: str
    sources: List[Source]


class DeepThoughtPacket(BaseModel):
    thesis: str
    outline: List[str]
    key_points: List[str]
    cautions: List[str]
    cta_options: List[str]


class ScribeLinkedInResponse(BaseModel):
    post: str
    post_draft: str
    voice_notes: Optional[str] = None
    citations: List[Source]
    research_packet: ResearchPacket
    deep_thought: DeepThoughtPacket


VOICE_RULES = """You are Staff:Scribe.

Voice (Bart de Graaff / BdGAdvisory):
- Controlled but human; reflective, not performative.
- Calm, precise, measured. Executive tone.
- No hype, no clichés, no LinkedIn theater.

Frame:
- Structural lens: incentives, governance, capital pressure, commercial sequencing shape execution.
- Authority through pattern recognition and lived experience (operator–builder), not assertion.

Format:
- Mobile-friendly line breaks.
- Short paragraphs.
- Clear claim early, supported by grounded observations.
- End with a crisp takeaway or thoughtful question.
- Do not fabricate facts; cite only what is supported by provided sources.
"""


def scout(topic: str, angle: Optional[str], num_sources: int) -> ResearchPacket:
    q = topic.strip()
    if angle:
        q = f"{q} {angle.strip()}"
    q = f"{q} incentives governance capital execution"
    sources = serper_search(q, num=num_sources)
    return ResearchPacket(query=q, sources=sources)


def deep_thought(topic: str, angle: Optional[str], audience: Optional[str], research: ResearchPacket) -> DeepThoughtPacket:
    client = _anthropic_client()
    model = _model("DEEPTHOUGHT_MODEL", DEFAULT_SONNET)

    source_block = "\n".join(
        [f"- {s.title}\n  {s.link}\n  {s.snippet or ''}".strip() for s in research.sources]
    )

    prompt = f"""Create a planning packet for a LinkedIn post.

Topic: {topic}
Angle: {angle or "none"}
Audience: {audience or "none"}

Use these sources as the factual substrate (do not invent specifics):
{source_block}

Return JSON ONLY with keys:
- thesis (string)
- outline (array of strings)
- key_points (array of strings)
- cautions (array of strings)
- cta_options (array of strings)
"""

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=700,
            temperature=0.3,
            system=VOICE_RULES,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join([b.text for b in msg.content if getattr(b, "type", None) == "text"]).strip()
        import json
        data = json.loads(text)
        return DeepThoughtPacket(**data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Deep Thought failed: {repr(e)}")


def quill(topic: str, angle: Optional[str], audience: Optional[str], research: ResearchPacket, plan: DeepThoughtPacket) -> str:
    client = _anthropic_client()
    model = _model("QUILL_MODEL", DEFAULT_SONNET)

    citations = "\n".join([f"- {s.title} ({s.link})" for s in research.sources])

    prompt = f"""Write the final LinkedIn post using the plan below.

Topic: {topic}
Angle: {angle or "none"}
Audience: {audience or "none"}

Plan JSON:
{plan.model_dump_json(indent=2)}

Citations (for consistency; do not add new facts):
{citations}

Output ONLY the post text.
"""

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=900,
            temperature=0.5,
            system=VOICE_RULES,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join([b.text for b in msg.content if getattr(b, "type", None) == "text"]).strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Quill failed: {repr(e)}")


def voice_pass(topic: str, angle: Optional[str], audience: Optional[str], plan: DeepThoughtPacket, draft_post: str) -> tuple[str, str]:
    """
    Voice = Scribe-owned consistency pass:
    - enforces tone + formatting + clarity
    - does not introduce new facts
    """
    client = _anthropic_client()
    model = _model("VOICE_MODEL", DEFAULT_SONNET)

    prompt = f"""You are Voice. Improve the draft ONLY for voice, clarity, and LinkedIn readability.

Constraints:
- Keep the core meaning.
- Do NOT add new factual claims.
- Do NOT add hype language.
- Enforce BdGAdvisory tone and structural lens.
- End with a crisp takeaway or thoughtful question.

Context:
Topic: {topic}
Angle: {angle or "none"}
Audience: {audience or "none"}

Plan (for intent):
{plan.model_dump_json(indent=2)}

Draft post:
{draft_post}

Return TWO sections exactly:

[POST]
<final post text>

[NOTES]
<brief bullet notes of what you changed and why>
"""

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=700,
            temperature=0.2,
            system=VOICE_RULES,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join([b.text for b in msg.content if getattr(b, "type", None) == "text"]).strip()

        def extract(tag: str) -> str:
            start = text.find(f"[{tag}]")
            if start == -1:
                return ""
            start += len(tag) + 2
            # find next tag
            next_tags = []
            for t in ("POST", "NOTES"):
                if t == tag:
                    continue
                idx = text.find(f"[{t}]", start)
                if idx != -1:
                    next_tags.append(idx)
            end = min(next_tags) if next_tags else len(text)
            return text[start:end].strip()

        post = extract("POST") or draft_post
        notes = extract("NOTES") or ""
        return post, notes
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Voice failed: {repr(e)}")


@router.post("/linkedin", response_model=ScribeLinkedInResponse)
def scribe_linkedin(payload: ScribeLinkedInRequest):
    research = scout(payload.topic, payload.angle, payload.num_sources)
    plan = deep_thought(payload.topic, payload.angle, payload.audience, research)
    draft = quill(payload.topic, payload.angle, payload.audience, research, plan)

    final_post = draft
    voice_notes: Optional[str] = None
    if payload.voice:
        final_post, voice_notes = voice_pass(payload.topic, payload.angle, payload.audience, plan, draft)

    return ScribeLinkedInResponse(
        post=final_post,
        post_draft=draft,
        voice_notes=voice_notes,
        citations=research.sources,
        research_packet=research,
        deep_thought=plan,
    )
