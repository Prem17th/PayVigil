"""Configuration presence only; provider verification is recorded separately."""

from fastapi import APIRouter, Depends

from app.core.auth import require_finance
from app.evidence.config import EvidenceSettings, get_evidence_settings
from app.core.schemas import Principal
from app.integrations.settings import SponsorSettings, get_sponsor_settings

router = APIRouter(prefix="/api")


@router.get("/integrations")
async def integrations(
    principal: Principal = Depends(require_finance),
    evidence: EvidenceSettings = Depends(get_evidence_settings),
    sponsors: SponsorSettings = Depends(get_sponsor_settings),
):
    return {
        "integrations": [
            {"id": key, "name": name, "configured": bool(configured), "live_verified": False}
            for key, name, configured in (
                ("openai", "OpenAI", evidence.openai_configured),
                ("n8n", "n8n", sponsors.n8n_configured),
                ("breeth", "Breeth AI", evidence.breeth_configured),
                ("elevenlabs", "ElevenLabs", sponsors.voice_configured),
                ("dodo", "Dodo Payments · test mode", sponsors.billing_configured),
            )
        ]
    }
