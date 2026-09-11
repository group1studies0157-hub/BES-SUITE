"""
gui/ai_provider.py
──────────────────
Unified AI provider wrapper for Bridge Engineering Suite.
Supports:  Anthropic Claude  |  Google Gemini

Dual-key fallback mode
──────────────────────
Pass BOTH gemini_key and claude_key to AIProvider; the class will:
  1. Try Gemini first (if gemini_key is provided and google-generativeai is installed)
  2. Fall back to Claude automatically on any Gemini failure
  3. Raise only if both providers fail

Single-key mode (backward-compatible)
──────────────────────────────────────
  provider = AIProvider(api_key, provider_name)   # original usage unchanged
  text = provider.chat(system_prompt, user_text)

Dual-key mode (new)
────────────────────
  provider = AIProvider.dual(gemini_key, claude_key)
  text = provider.chat(system_prompt, user_text)   # Gemini first, Claude fallback
"""

import base64, re

# ── Model IDs ──────────────────────────────────────────────────────────────
# Updated 2026-07-06: claude-sonnet-4-6 → claude-sonnet-5 (current default Sonnet);
# gemini-2.0-flash was retired 2026-06-01 → gemini-2.5-flash (current stable).
ANTHROPIC_MODEL = "claude-sonnet-5"
GEMINI_MODEL    = "gemini-2.5-flash"

# ── Provider name constants ─────────────────────────────────────────────────
PROVIDER_ANTHROPIC = "Anthropic (Claude)"
PROVIDER_GEMINI    = "Google (Gemini)"
PROVIDERS          = [PROVIDER_ANTHROPIC, PROVIDER_GEMINI]

def _anthropic_text(resp) -> str:
    """Join only the text blocks of a Messages response.
    Newer models (Sonnet 5+) may emit a ThinkingBlock before the TextBlock,
    so resp.content[0].text is no longer safe."""
    return "".join(
        b.text for b in resp.content
        if getattr(b, "type", "") == "text" or hasattr(b, "text")
    )

def detect_provider(api_key: str) -> str:
    """Auto-detect provider from key prefix."""
    if not api_key:
        return PROVIDER_ANTHROPIC
    if api_key.startswith("sk-ant"):
        return PROVIDER_ANTHROPIC
    if api_key.startswith("AIza"):
        return PROVIDER_GEMINI
    return PROVIDER_ANTHROPIC   # default


def _gemini_available() -> bool:
    """Return True if google-generativeai package is installed."""
    try:
        import google.generativeai  # noqa: F401
        return True
    except ImportError:
        return False


class AIProvider:
    """
    Single class that wraps both Anthropic and Gemini APIs.

    Two construction modes:
      AIProvider(api_key, provider)          — single key (original)
      AIProvider.dual(gemini_key, claude_key) — dual key with auto-fallback
    """

    def __init__(self, api_key: str, provider: str = "",
                 _gemini_key: str = "", _claude_key: str = "",
                 _dual_mode: bool = False):
        self.api_key     = api_key
        self.provider    = provider or detect_provider(api_key)
        # dual-mode extras
        self._dual_mode  = _dual_mode
        self._gemini_key = _gemini_key
        self._claude_key = _claude_key

    # ── Dual-key factory ───────────────────────────────────────────────────
    @classmethod
    def dual(cls, gemini_key: str, claude_key: str) -> "AIProvider":
        """
        Create a provider that tries Gemini first and falls back to Claude.
        Either key may be empty — the class skips that provider gracefully.
        """
        # Primary key for backward-compat display; prefer Gemini if present
        primary_key      = gemini_key or claude_key
        primary_provider = PROVIDER_GEMINI if gemini_key else PROVIDER_ANTHROPIC
        return cls(
            api_key      = primary_key,
            provider     = primary_provider,
            _gemini_key  = gemini_key,
            _claude_key  = claude_key,
            _dual_mode   = True,
        )

    # ── Internal: run with Gemini-first fallback ───────────────────────────
    def _run_with_fallback(self, gemini_fn, claude_fn):
        """
        Execute gemini_fn(); if it raises (missing package, quota, auth, etc.)
        log the reason and execute claude_fn() instead.
        Returns the result of whichever function succeeded.
        """
        if self._dual_mode:
            gemini_reason = None   # track why Gemini was skipped / failed

            # Try Gemini first
            if self._gemini_key:
                if not _gemini_available():
                    gemini_reason = (
                        "google-generativeai not installed — "
                        "run: pip install google-generativeai"
                    )
                else:
                    try:
                        return gemini_fn()
                    except Exception as gemini_err:
                        gemini_reason = str(gemini_err)   # store on local var, not discarded
            else:
                gemini_reason = "no Gemini key provided"

            # Try Claude fallback
            if self._claude_key:
                try:
                    return claude_fn()
                except Exception as claude_err:
                    raise RuntimeError(
                        f"Both providers failed.\n"
                        f"Gemini: {gemini_reason}\n"
                        f"Claude: {claude_err}"
                    )
            raise RuntimeError(
                "No API keys configured. Please add at least one API key in Settings."
            )
        # Single-key mode — original behaviour
        if self.provider == PROVIDER_GEMINI:
            return gemini_fn()
        return claude_fn()

    # ── Plain text generation ──────────────────────────────────────────────
    def chat(self, system: str, user: str, max_tokens: int = 4000) -> str:
        def _gemini():
            return self._gemini_chat_key(self._gemini_key, system, user, max_tokens)
        def _claude():
            return self._anthropic_chat_key(self._claude_key, system, user, max_tokens)

        if self._dual_mode:
            return self._run_with_fallback(_gemini, _claude)
        if self.provider == PROVIDER_GEMINI:
            return self._gemini_chat(system, user, max_tokens)
        return self._anthropic_chat(system, user, max_tokens)

    # ── Vision: image ──────────────────────────────────────────────────────
    def vision(self, system: str, image_b64: str, mime: str,
               user: str, max_tokens: int = 4000) -> str:
        def _gemini():
            return self._gemini_vision_key(self._gemini_key, system, image_b64, mime, user, max_tokens)
        def _claude():
            return self._anthropic_vision_key(self._claude_key, system, image_b64, mime, user, max_tokens)

        if self._dual_mode:
            return self._run_with_fallback(_gemini, _claude)
        if self.provider == PROVIDER_GEMINI:
            return self._gemini_vision(system, image_b64, mime, user, max_tokens)
        return self._anthropic_vision(system, image_b64, mime, user, max_tokens)

    # ── Vision: PDF ────────────────────────────────────────────────────────
    def vision_pdf(self, system: str, pdf_b64: str,
                   user: str, max_tokens: int = 4000) -> str:
        def _gemini():
            return self._gemini_vision_key(self._gemini_key, system, pdf_b64,
                                           "application/pdf", user, max_tokens)
        def _claude():
            return self._anthropic_vision_pdf_key(self._claude_key, system, pdf_b64, user, max_tokens)

        if self._dual_mode:
            return self._run_with_fallback(_gemini, _claude)
        if self.provider == PROVIDER_GEMINI:
            return self._gemini_vision(system, pdf_b64, "application/pdf", user, max_tokens)
        return self._anthropic_vision_pdf(system, pdf_b64, user, max_tokens)

    # ══════════════════════════════════════════════════════════════════════
    # ANTHROPIC BACKENDS  (original single-key variants)
    # ══════════════════════════════════════════════════════════════════════
    def _anthropic_chat(self, system, user, max_tokens):
        return self._anthropic_chat_key(self.api_key, system, user, max_tokens)

    def _anthropic_vision(self, system, image_b64, mime, user, max_tokens):
        return self._anthropic_vision_key(self.api_key, system, image_b64, mime, user, max_tokens)

    def _anthropic_vision_pdf(self, system, pdf_b64, user, max_tokens):
        return self._anthropic_vision_pdf_key(self.api_key, system, pdf_b64, user, max_tokens)

    # ── Anthropic key-explicit variants (used by dual mode) ───────────────
    @staticmethod
    def _anthropic_chat_key(api_key, system, user, max_tokens):
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}]
        )
        return _anthropic_text(resp)

    @staticmethod
    def _anthropic_vision_key(api_key, system, image_b64, mime, user, max_tokens):
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": [
                {"type": "image",
                 "source": {"type": "base64",
                            "media_type": mime,
                            "data": image_b64}},
                {"type": "text", "text": user}
            ]}]
        )
        return _anthropic_text(resp)

    @staticmethod
    def _anthropic_vision_pdf_key(api_key, system, pdf_b64, user, max_tokens):
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": [
                {"type": "document",
                 "source": {"type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64}},
                {"type": "text", "text": user}
            ]}]
        )
        return _anthropic_text(resp)

    # ══════════════════════════════════════════════════════════════════════
    # GEMINI BACKENDS  (original single-key variants)
    # ══════════════════════════════════════════════════════════════════════
    def _gemini_client(self):
        return self._gemini_client_for_key(self.api_key)

    def _gemini_chat(self, system, user, max_tokens):
        return self._gemini_chat_key(self.api_key, system, user, max_tokens)

    def _gemini_vision(self, system, image_b64, mime, user, max_tokens):
        return self._gemini_vision_key(self.api_key, system, image_b64, mime, user, max_tokens)

    # ── Gemini key-explicit variants (used by dual mode) ──────────────────
    @staticmethod
    def _gemini_client_for_key(api_key, max_tokens: int = 4096):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package is not installed.\n"
                "Run:  pip install google-generativeai\n"
                "The app will automatically fall back to Claude if a Claude key is also set."
            )
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            generation_config={"max_output_tokens": max(int(max_tokens), 256),
                               "temperature": 0.3}
        )

    @staticmethod
    def _gemini_chat_key(api_key, system, user, max_tokens):
        model = AIProvider._gemini_client_for_key(api_key, max_tokens)
        resp  = model.generate_content(f"{system}\n\n{user}")
        return resp.text

    @staticmethod
    def _gemini_vision_key(api_key, system, image_b64, mime, user, max_tokens):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package is not installed.\n"
                "Run:  pip install google-generativeai"
            )
        model = AIProvider._gemini_client_for_key(api_key, max_tokens)
        blob  = genai.protos.Blob(
            mime_type=mime,
            data=base64.b64decode(image_b64)
        )
        resp = model.generate_content([f"{system}\n\n{user}", blob])
        return resp.text
