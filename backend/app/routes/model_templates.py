"""
Model Template routes — CRUD + built-in seed data.
"""
from datetime import datetime
from flask import Blueprint, request, jsonify

from app import db
from app.models import ModelTemplate
from app.routes.users import token_required

model_templates_bp = Blueprint('model_templates', __name__)

# ---------------------------------------------------------------------------
# Built-in seed data
# ---------------------------------------------------------------------------
BUILTIN_TEMPLATES = [
    # ── OpenAI ──────────────────────────────────────────────────────────────
    dict(label='GPT-5.4', provider='OpenAI', name='gpt-5.4', alias='gpt-5.4',
         context_size=272000, input_size=272000, output_size=8192,
         pricing_tiers=[
             dict(label='<=272k ctx', context_size=272000, input_size=272000, output_size=8192,
                  input_price=2.5, output_price=15, cache_creation_price=0, cache_hit_price=0.25),
             dict(label='>272k ctx', context_size=1000000, input_size=1000000, output_size=8192,
                  input_price=5, output_price=22, cache_creation_price=0, cache_hit_price=0.5),
         ],
         input_price=2.5, output_price=15, cache_creation_price=0, cache_hit_price=0.25,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=True,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.4 mini', provider='OpenAI', name='gpt-5.4-mini', alias='gpt-5.4-mini',
         context_size=272000, input_size=272000, output_size=8192, pricing_tiers=None,
         input_price=0.75, output_price=4.5, cache_creation_price=0, cache_hit_price=0.075,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=True,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.4 Pro', provider='OpenAI', name='gpt-5.4-pro', alias='gpt-5.4-pro',
         context_size=272000, input_size=272000, output_size=8192,
         pricing_tiers=[
             dict(label='<=272k ctx', context_size=272000, input_size=272000, output_size=8192,
                  input_price=30, output_price=180, cache_creation_price=0, cache_hit_price=0),
             dict(label='>272k ctx', context_size=1000000, input_size=1000000, output_size=8192,
                  input_price=60, output_price=270, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=30, output_price=180, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=True,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.3 Codex', provider='OpenAI', name='gpt-5.3-codex', alias='gpt-5.3-codex',
         context_size=400000, input_size=400000, output_size=128000, pricing_tiers=None,
         input_price=1.75, output_price=14, cache_creation_price=0, cache_hit_price=0.175,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.3 Chat', provider='OpenAI', name='gpt-5.3-chat', alias='gpt-5.3-chat',
         context_size=128000, input_size=128000, output_size=16384, pricing_tiers=None,
         input_price=1.75, output_price=14, cache_creation_price=0, cache_hit_price=0.175,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.2', provider='OpenAI', name='gpt-5.2', alias='gpt-5.2',
         context_size=272000, input_size=272000, output_size=8192, pricing_tiers=None,
         input_price=1.75, output_price=14, cache_creation_price=0, cache_hit_price=0.175,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.2 Pro', provider='OpenAI', name='gpt-5.2-pro', alias='gpt-5.2-pro',
         context_size=272000, input_size=272000, output_size=8192, pricing_tiers=None,
         input_price=21, output_price=168, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.1', provider='OpenAI', name='gpt-5.1', alias='gpt-5.1',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=1.25, output_price=10, cache_creation_price=0, cache_hit_price=0.125,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5', provider='OpenAI', name='gpt-5', alias='gpt-5',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=1.25, output_price=10, cache_creation_price=0, cache_hit_price=0.125,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5 mini', provider='OpenAI', name='gpt-5-mini', alias='gpt-5-mini',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=0.25, output_price=2, cache_creation_price=0, cache_hit_price=0.025,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5 Pro', provider='OpenAI', name='gpt-5-pro', alias='gpt-5-pro',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=15, output_price=120, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-4.1', provider='OpenAI', name='gpt-4.1', alias='gpt-4.1',
         context_size=1000000, input_size=1000000, output_size=8192, pricing_tiers=None,
         input_price=2, output_price=8, cache_creation_price=0, cache_hit_price=0.5,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-4.1 mini', provider='OpenAI', name='gpt-4.1-mini', alias='gpt-4.1-mini',
         context_size=1000000, input_size=1000000, output_size=8192, pricing_tiers=None,
         input_price=0.4, output_price=1.6, cache_creation_price=0, cache_hit_price=0.1,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='text-embedding-3-large', provider='OpenAI', name='text-embedding-3-large', alias='embedding-large',
         context_size=8191, input_size=8191, output_size=4096, pricing_tiers=None,
         input_price=0.13, output_price=0, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=True),
    dict(label='text-embedding-3-small', provider='OpenAI', name='text-embedding-3-small', alias='embedding-small',
         context_size=8191, input_size=8191, output_size=4096, pricing_tiers=None,
         input_price=0.02, output_price=0, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=True),
    # ── Azure OpenAI ────────────────────────────────────────────────────────
    dict(label='GPT-5.4 (Azure)', provider='Azure', name='gpt-5.4', alias='gpt-5.4',
         context_size=272000, input_size=272000, output_size=8192,
         pricing_tiers=[
             dict(label='<=272k ctx', context_size=272000, input_size=272000, output_size=8192,
                  input_price=2.5, output_price=15, cache_creation_price=0, cache_hit_price=0.25),
             dict(label='>272k ctx', context_size=1000000, input_size=1000000, output_size=8192,
                  input_price=5, output_price=22, cache_creation_price=0, cache_hit_price=0.5),
         ],
         input_price=2.5, output_price=15, cache_creation_price=0, cache_hit_price=0.25,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=True,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.4 mini (Azure)', provider='Azure', name='gpt-5.4-mini', alias='gpt-5.4-mini',
         context_size=272000, input_size=272000, output_size=8192, pricing_tiers=None,
         input_price=0.75, output_price=4.5, cache_creation_price=0, cache_hit_price=0.075,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=True,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.4 Pro (Azure)', provider='Azure', name='gpt-5.4-pro', alias='gpt-5.4-pro',
         context_size=272000, input_size=272000, output_size=8192,
         pricing_tiers=[
             dict(label='<=272k ctx', context_size=272000, input_size=272000, output_size=8192,
                  input_price=30, output_price=180, cache_creation_price=0, cache_hit_price=0),
             dict(label='>272k ctx', context_size=1000000, input_size=1000000, output_size=8192,
                  input_price=60, output_price=270, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=30, output_price=180, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=True,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.3 Codex (Azure)', provider='Azure', name='gpt-5.3-codex', alias='gpt-5.3-codex',
         context_size=400000, input_size=400000, output_size=128000, pricing_tiers=None,
         input_price=1.75, output_price=14, cache_creation_price=0, cache_hit_price=0.175,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.3 Chat (Azure)', provider='Azure', name='gpt-5.3-chat', alias='gpt-5.3-chat',
         context_size=128000, input_size=128000, output_size=16384, pricing_tiers=None,
         input_price=1.75, output_price=14, cache_creation_price=0, cache_hit_price=0.175,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.2 (Azure)', provider='Azure', name='gpt-5.2', alias='gpt-5.2',
         context_size=272000, input_size=272000, output_size=8192, pricing_tiers=None,
         input_price=1.75, output_price=14, cache_creation_price=0, cache_hit_price=0.175,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.2 Pro (Azure)', provider='Azure', name='gpt-5.2-pro', alias='gpt-5.2-pro',
         context_size=272000, input_size=272000, output_size=8192, pricing_tiers=None,
         input_price=21, output_price=168, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5.1 (Azure)', provider='Azure', name='gpt-5.1', alias='gpt-5.1',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=1.25, output_price=10, cache_creation_price=0, cache_hit_price=0.125,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5 (Azure)', provider='Azure', name='gpt-5', alias='gpt-5',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=1.25, output_price=10, cache_creation_price=0, cache_hit_price=0.125,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5 mini (Azure)', provider='Azure', name='gpt-5-mini', alias='gpt-5-mini',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=0.25, output_price=2, cache_creation_price=0, cache_hit_price=0.025,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-5 Pro (Azure)', provider='Azure', name='gpt-5-pro', alias='gpt-5-pro',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=15, output_price=120, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-4.1 (Azure)', provider='Azure', name='gpt-4.1', alias='gpt-4.1',
         context_size=1000000, input_size=1000000, output_size=8192, pricing_tiers=None,
         input_price=2, output_price=8, cache_creation_price=0, cache_hit_price=0.5,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GPT-4.1 mini (Azure)', provider='Azure', name='gpt-4.1-mini', alias='gpt-4.1-mini',
         context_size=1000000, input_size=1000000, output_size=8192, pricing_tiers=None,
         input_price=0.4, output_price=1.6, cache_creation_price=0, cache_hit_price=0.1,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='text-embedding-3-large (Azure)', provider='Azure', name='text-embedding-3-large', alias='embedding-large',
         context_size=8191, input_size=8191, output_size=4096, pricing_tiers=None,
         input_price=0.13, output_price=0, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=True),
    dict(label='text-embedding-3-small (Azure)', provider='Azure', name='text-embedding-3-small', alias='embedding-small',
         context_size=8191, input_size=8191, output_size=4096, pricing_tiers=None,
         input_price=0.02, output_price=0, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=True),
    # ── Anthropic ────────────────────────────────────────────────────────────
    dict(label='Claude Opus 4.6', provider='Anthropic', name='claude-opus-4-6', alias='claude-opus-4',
         context_size=200000, input_size=200000, output_size=8192, pricing_tiers=None,
         input_price=5, output_price=25, cache_creation_price=6.25, cache_hit_price=0.5,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=True, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='Claude Sonnet 4.6', provider='Anthropic', name='claude-sonnet-4-6', alias='claude-sonnet-4',
         context_size=200000, input_size=200000, output_size=8192, pricing_tiers=None,
         input_price=3, output_price=15, cache_creation_price=3.75, cache_hit_price=0.3,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=True, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='Claude Haiku 4.5', provider='Anthropic', name='claude-haiku-4-5', alias='claude-haiku-4-5',
         context_size=200000, input_size=200000, output_size=8192, pricing_tiers=None,
         input_price=1, output_price=4, cache_creation_price=1.25, cache_hit_price=0.1,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=True, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    # ── Google Gemini ────────────────────────────────────────────────────────
    dict(label='Gemini 2.5 Pro', provider='Google', name='gemini-2.5-pro-preview-03-25', alias='gemini-2.5-pro',
         context_size=1048576, input_size=1048576, output_size=8192, pricing_tiers=None,
         input_price=1.25, output_price=10, cache_creation_price=0, cache_hit_price=0.31,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=True, support_embedding=False),
    dict(label='Gemini 3.1 Pro Preview', provider='Google', name='gemini-3.1-pro-preview', alias='gemini-3.1-pro-preview',
         context_size=1048576, input_size=1048576, output_size=65536,
         pricing_tiers=[
             dict(label='<=200k', context_size=1048576, input_size=204800, output_size=65536,
                  input_price=2, output_price=12, cache_creation_price=0, cache_hit_price=0.2),
             dict(label='>200k', context_size=1048576, input_size=1048576, output_size=65536,
                  input_price=4, output_price=18, cache_creation_price=0, cache_hit_price=0.4),
         ],
         input_price=2, output_price=12, cache_creation_price=0, cache_hit_price=0.2,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=True, support_embedding=False),
    dict(label='Gemini 3.1 Flash Lite', provider='Google', name='gemini-3.1-flash-lite', alias='gemini-3.1-flash-lite',
         context_size=1048576, input_size=1048576, output_size=65536, pricing_tiers=None,
         input_price=0.25, output_price=1.5, cache_creation_price=0, cache_hit_price=0.03,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False),
    dict(label='Gemini 3 Pro Preview', provider='Google', name='gemini-3-pro-preview', alias='gemini-3-pro-preview',
         context_size=1048576, input_size=1048576, output_size=65536,
         pricing_tiers=[
             dict(label='<=200k', context_size=1048576, input_size=204800, output_size=65536,
                  input_price=2, output_price=12, cache_creation_price=0, cache_hit_price=0.2),
             dict(label='>200k', context_size=1048576, input_size=1048576, output_size=65536,
                  input_price=4, output_price=18, cache_creation_price=0, cache_hit_price=0.4),
         ],
         input_price=2, output_price=12, cache_creation_price=0, cache_hit_price=0.2,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=True, support_embedding=False),
    dict(label='Gemini 3 Flash Preview', provider='Google', name='gemini-3-flash-preview', alias='gemini-3-flash-preview',
         context_size=1048576, input_size=1048576, output_size=65536, pricing_tiers=None,
         input_price=0.5, output_price=3, cache_creation_price=0, cache_hit_price=0.05,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False),
    # ── Google Gemini Image ─────────────────────────────────────────────────
    # Gemini native image generation models — per-image pricing (USD).
    # Input/output token prices are also listed for multimodal prompt cost.
    dict(
        label='Gemini 3.1 Flash Image Preview',
        provider='Google',
        name='gemini-3.1-flash-image-preview',
        alias='gemini-3.1-flash-image-preview',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '512x512,1024x1024,2048x2048,4096x4096,'
            '256x1024,512x2048,1024x4096,2048x8192,'
            '192x1536,384x3072,768x6144,1536x12288,'
            '424x632,848x1264,1696x2528,3392x5056,'
            '632x424,1264x848,2528x1696,5056x3392,'
            '448x600,896x1200,1792x2400,3584x4800,'
            '1024x256,2048x512,4096x1024,8192x2048,'
            '600x448,1200x896,2400x1792,4800x3584,'
            '464x576,928x1152,1856x2304,3712x4608,'
            '576x464,1152x928,2304x1856,4608x3712,'
            '1536x192,3072x384,6144x768,12288x1536,'
            '384x688,768x1376,1536x2752,3072x5504,'
            '688x384,1376x768,2752x1536,5504x3072,'
            '792x168,1584x672,3168x1344,6336x2688'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.067,
                'tiers': [
                    {'resolution': '512', 'price': 0.045},
                    {'resolution': '1K', 'price': 0.067},
                    {'resolution': '2K', 'price': 0.101},
                    {'resolution': '4K', 'price': 0.15},
                ],
            },
        },
        input_price=0.5, output_price=0.3, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Gemini 3 Pro Image Preview',
        provider='Google',
        name='gemini-3-pro-image-preview',
        alias='gemini-3-pro-image-preview',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '1024x1024,2048x2048,4096x4096,'
            '848x1264,1696x2528,3392x5056,'
            '1264x848,2528x1696,5056x3392,'
            '896x1200,1792x2400,3584x4800,'
            '1200x896,2400x1792,4800x3584,'
            '928x1152,1856x2304,3712x4608,'
            '1152x928,2304x1856,4608x3712,'
            '768x1376,1536x2752,3072x5504,'
            '1376x768,2752x1536,5504x3072,'
            '1584x672,3168x1344,6336x2688'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.134,
                'tiers': [
                    {'resolution': '1K', 'price': 0.134},
                    {'resolution': '2K', 'price': 0.134},
                    {'resolution': '4K', 'price': 0.24},
                ],
            },
        },
        input_price=2, output_price=12, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Gemini 2.5 Flash Image',
        provider='Google',
        name='gemini-2.5-flash-image',
        alias='gemini-2.5-flash-image',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats='1024x1024,832x1248,1248x832,864x1184,1184x864,896x1152,1152x896,768x1344,1344x768,1536x672',
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.0336,
                'tiers': [
                    {'resolution': '1K', 'price': 0.0336},
                    {'resolution': '2K', 'price': 0.0336},
                    {'resolution': '4K', 'price': 0.06},
                ],
            },
        },
        input_price=0.3, output_price=2.5, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # ── VertexAI Gemini Image ───────────────────────────────────────────────
    # Same Gemini image models via Vertex AI — same USD pricing.
    dict(
        label='Gemini 3.1 Flash Image Preview (VertexAI)',
        provider='VertexAI',
        name='gemini-3.1-flash-image-preview',
        alias='gemini-3.1-flash-image-preview',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '512x512,1024x1024,2048x2048,4096x4096,'
            '256x1024,512x2048,1024x4096,2048x8192,'
            '192x1536,384x3072,768x6144,1536x12288,'
            '424x632,848x1264,1696x2528,3392x5056,'
            '632x424,1264x848,2528x1696,5056x3392,'
            '448x600,896x1200,1792x2400,3584x4800,'
            '1024x256,2048x512,4096x1024,8192x2048,'
            '600x448,1200x896,2400x1792,4800x3584,'
            '464x576,928x1152,1856x2304,3712x4608,'
            '576x464,1152x928,2304x1856,4608x3712,'
            '1536x192,3072x384,6144x768,12288x1536,'
            '384x688,768x1376,1536x2752,3072x5504,'
            '688x384,1376x768,2752x1536,5504x3072,'
            '792x168,1584x672,3168x1344,6336x2688'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.067,
                'tiers': [
                    {'resolution': '512', 'price': 0.045},
                    {'resolution': '1K', 'price': 0.067},
                    {'resolution': '2K', 'price': 0.101},
                    {'resolution': '4K', 'price': 0.15},
                ],
            },
        },
        input_price=0.5, output_price=0.3, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Gemini 3 Pro Image Preview (VertexAI)',
        provider='VertexAI',
        name='gemini-3-pro-image-preview',
        alias='gemini-3-pro-image-preview',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '1024x1024,2048x2048,4096x4096,'
            '848x1264,1696x2528,3392x5056,'
            '1264x848,2528x1696,5056x3392,'
            '896x1200,1792x2400,3584x4800,'
            '1200x896,2400x1792,4800x3584,'
            '928x1152,1856x2304,3712x4608,'
            '1152x928,2304x1856,4608x3712,'
            '768x1376,1536x2752,3072x5504,'
            '1376x768,2752x1536,5504x3072,'
            '1584x672,3168x1344,6336x2688'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.134,
                'tiers': [
                    {'resolution': '1K', 'price': 0.134},
                    {'resolution': '2K', 'price': 0.134},
                    {'resolution': '4K', 'price': 0.24},
                ],
            },
        },
        input_price=2, output_price=12, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Gemini 2.5 Flash Image (VertexAI)',
        provider='VertexAI',
        name='gemini-2.5-flash-image',
        alias='gemini-2.5-flash-image',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats='1024x1024,832x1248,1248x832,864x1184,1184x864,896x1152,1152x896,768x1344,1344x768,1536x672',
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.0336,
                'tiers': [
                    {'resolution': '1K', 'price': 0.0336},
                    {'resolution': '2K', 'price': 0.0336},
                    {'resolution': '4K', 'price': 0.06},
                ],
            },
        },
        input_price=0.3, output_price=2.5, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # ── DeepSeek ─────────────────────────────────────────────────────────────
    dict(label='DeepSeek V3 (Official)', provider='DeepSeek', name='deepseek-chat', alias='deepseek-v3',
         context_size=128000, input_size=128000, output_size=8000, pricing_tiers=None,
         input_price=2, output_price=3, cache_creation_price=0, cache_hit_price=0.2,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='DeepSeek R1 (Official)', provider='DeepSeek', name='deepseek-reasoner', alias='deepseek-r1',
         context_size=128000, input_size=128000, output_size=64000, pricing_tiers=None,
         input_price=2, output_price=3, cache_creation_price=0, cache_hit_price=0.2,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    # ── Moonshot (Kimi) ──────────────────────────────────────────────────────
    dict(label='Kimi K2.5', provider='Moonshot', name='kimi-k2.5', alias='kimi-k2.5',
         context_size=262144, input_size=262144, output_size=65536, pricing_tiers=None,
         input_price=4, output_price=21, cache_creation_price=0, cache_hit_price=0.7,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Kimi K2 Turbo Preview', provider='Moonshot', name='kimi-k2-turbo-preview', alias='kimi-k2-turbo-preview',
         context_size=262144, input_size=262144, output_size=65536, pricing_tiers=None,
         input_price=8, output_price=58, cache_creation_price=0, cache_hit_price=1,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Kimi K2 0905 Preview', provider='Moonshot', name='kimi-k2-0905-preview', alias='kimi-k2-0905-preview',
         context_size=262144, input_size=262144, output_size=65536, pricing_tiers=None,
         input_price=4, output_price=16, cache_creation_price=0, cache_hit_price=1,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Kimi K2 Thinking', provider='Moonshot', name='kimi-k2-thinking', alias='kimi-k2-thinking',
         context_size=262144, input_size=262144, output_size=65536, pricing_tiers=None,
         input_price=4, output_price=16, cache_creation_price=0, cache_hit_price=1,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Kimi K2 Thinking Turbo', provider='Moonshot', name='kimi-k2-thinking-turbo', alias='kimi-k2-thinking-turbo',
         context_size=262144, input_size=262144, output_size=65536, pricing_tiers=None,
         input_price=8, output_price=58, cache_creation_price=0, cache_hit_price=1,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    # ── GLM (Zhipu AI) ───────────────────────────────────────────────────────
    dict(label='GLM-5', provider='Bailian', name='glm-5', alias='glm-5',
         context_size=202752, input_size=202752, output_size=16384,
         pricing_tiers=[
             dict(label='0~32k', context_size=202752, input_size=32768, output_size=16384,
                  input_price=4, output_price=18, cache_creation_price=0, cache_hit_price=0),
             dict(label='32k~198k', context_size=202752, input_size=202752, output_size=16384,
                  input_price=6, output_price=22, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=4, output_price=18, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='GLM-4.7', provider='Bailian', name='glm-4.7', alias='glm-4.7',
         context_size=202752, input_size=169984, output_size=16384,
         pricing_tiers=[
             dict(label='0~32k', context_size=202752, input_size=32768, output_size=16384,
                  input_price=3, output_price=14, cache_creation_price=0, cache_hit_price=0),
             dict(label='32k~166k', context_size=202752, input_size=169984, output_size=16384,
                  input_price=4, output_price=16, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=3, output_price=14, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='GLM-4', provider='GLM', name='glm-4', alias='glm-4',
         context_size=128000, input_size=128000, output_size=4096, pricing_tiers=None,
         input_price=0.7, output_price=0.7, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='GLM-4V', provider='GLM', name='glm-4v', alias='glm-4v',
         context_size=8192, input_size=8192, output_size=4096, pricing_tiers=None,
         input_price=0.7, output_price=0.7, cache_creation_price=0, cache_hit_price=0,
         support_kvcache=False, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='GLM-5 Turbo', provider='GLM', name='glm-5-turbo', alias='glm-5-turbo',
         context_size=202752, input_size=202752, output_size=16384,
         pricing_tiers=[
             dict(label='0~32k', context_size=202752, input_size=32768, output_size=16384,
                  input_price=5, output_price=22, cache_creation_price=0, cache_hit_price=1.2),
             dict(label='>32k', context_size=202752, input_size=202752, output_size=16384,
                  input_price=7, output_price=26, cache_creation_price=0, cache_hit_price=1.8),
         ],
         input_price=5, output_price=22, cache_creation_price=0, cache_hit_price=1.2,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='GLM-5', provider='GLM', name='glm-5', alias='glm-5',
         context_size=202752, input_size=202752, output_size=16384,
         pricing_tiers=[
             dict(label='0~32k', context_size=202752, input_size=32768, output_size=16384,
                  input_price=4, output_price=18, cache_creation_price=0, cache_hit_price=1),
             dict(label='>32k', context_size=202752, input_size=202752, output_size=16384,
                  input_price=6, output_price=22, cache_creation_price=0, cache_hit_price=1.5),
         ],
         input_price=4, output_price=18, cache_creation_price=0, cache_hit_price=1,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='GLM-4.7', provider='GLM', name='glm-4.7', alias='glm-4.7',
         context_size=202752, input_size=202752, output_size=16384,
         pricing_tiers=[
             dict(label='0~32k', context_size=202752, input_size=32768, output_size=16384,
                  input_price=2, output_price=8, cache_creation_price=0, cache_hit_price=0.4),
             dict(label='>32k', context_size=202752, input_size=202752, output_size=16384,
                  input_price=4, output_price=16, cache_creation_price=0, cache_hit_price=0.8),
         ],
         input_price=2, output_price=8, cache_creation_price=0, cache_hit_price=0.4,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    # ── Bailian / Qwen ───────────────────────────────────────────────────────
    dict(label='Qwen3.6 Plus', provider='Bailian', name='qwen3.6-plus', alias='qwen3.6-plus',
         context_size=1000000, input_size=991808, output_size=65536,
         pricing_tiers=[
             dict(label='<=256k', context_size=1000000, input_size=262144, output_size=65536,
                  input_price=2, output_price=12, cache_creation_price=2.5, cache_hit_price=0.2),
             dict(label='256k~1M', context_size=1000000, input_size=991808, output_size=65536,
                  input_price=8, output_price=48, cache_creation_price=10, cache_hit_price=0.8),
         ],
         input_price=2, output_price=12, cache_creation_price=2.5, cache_hit_price=0.2,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=True, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Qwen3.5 Plus', provider='Bailian', name='qwen3.5-plus', alias='qwen3.5-plus',
         context_size=1000000, input_size=991808, output_size=65536,
         pricing_tiers=[
             dict(label='<128k', context_size=1000000, input_size=131072, output_size=65536,
                  input_price=0.8, output_price=4.8, cache_creation_price=0, cache_hit_price=0),
             dict(label='128k~256k', context_size=1000000, input_size=262144, output_size=65536,
                  input_price=2, output_price=12, cache_creation_price=0, cache_hit_price=0),
             dict(label='>256k', context_size=1000000, input_size=991808, output_size=65536,
                  input_price=4, output_price=24, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=0.8, output_price=4.8, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Qwen3.5 Flash', provider='Bailian', name='qwen3.5-flash', alias='qwen3.5-flash',
         context_size=1000000, input_size=991808, output_size=65536,
         pricing_tiers=[
             dict(label='<128k', context_size=1000000, input_size=131072, output_size=65536,
                  input_price=0.2, output_price=2, cache_creation_price=0, cache_hit_price=0),
             dict(label='128k~256k', context_size=1000000, input_size=262144, output_size=65536,
                  input_price=0.8, output_price=8, cache_creation_price=0, cache_hit_price=0),
             dict(label='>256k', context_size=1000000, input_size=991808, output_size=65536,
                  input_price=1.2, output_price=12, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=0.2, output_price=2, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Qwen Plus', provider='Bailian', name='qwen-plus', alias='qwen-plus',
         context_size=1000000, input_size=997952, output_size=32768,
         pricing_tiers=[
             dict(label='<128k', context_size=1000000, input_size=131072, output_size=32768,
                  input_price=0.8, output_price=2, cache_creation_price=0, cache_hit_price=0),
             dict(label='128k~256k', context_size=1000000, input_size=262144, output_size=32768,
                  input_price=2.4, output_price=20, cache_creation_price=0, cache_hit_price=0),
             dict(label='>256k', context_size=1000000, input_size=997952, output_size=32768,
                  input_price=4.8, output_price=48, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=0.8, output_price=2, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Qwen Flash', provider='Bailian', name='qwen-flash', alias='qwen-flash',
         context_size=1000000, input_size=997952, output_size=32768,
         pricing_tiers=[
             dict(label='<128k', context_size=1000000, input_size=131072, output_size=32768,
                  input_price=0.15, output_price=1.5, cache_creation_price=0, cache_hit_price=0),
             dict(label='128k~256k', context_size=1000000, input_size=262144, output_size=32768,
                  input_price=0.6, output_price=6, cache_creation_price=0, cache_hit_price=0),
             dict(label='>256k', context_size=1000000, input_size=997952, output_size=32768,
                  input_price=1.2, output_price=12, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=0.15, output_price=1.5, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Qwen Turbo', provider='Bailian', name='qwen-turbo', alias='qwen-turbo',
         context_size=1000000, input_size=1000000, output_size=16384, pricing_tiers=None,
         input_price=0.3, output_price=0.6, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Qwen Max', provider='Bailian', name='qwen-max', alias='qwen-max',
         context_size=8000, input_size=6000, output_size=2000, pricing_tiers=None,
         input_price=2.4, output_price=9.6, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Qwen3 VL Plus', provider='Bailian', name='qwen3-vl-plus', alias='qwen3-vl-plus',
         context_size=262144, input_size=258048, output_size=81920,
         pricing_tiers=[
             dict(label='<32k', context_size=262144, input_size=32768, output_size=81920,
                  input_price=1, output_price=10, cache_creation_price=0, cache_hit_price=0),
             dict(label='32k~128k', context_size=262144, input_size=131072, output_size=81920,
                  input_price=1.5, output_price=15, cache_creation_price=0, cache_hit_price=0),
             dict(label='>128k', context_size=262144, input_size=258048, output_size=81920,
                  input_price=3, output_price=30, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=1, output_price=10, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='Qwen3 Coder Plus', provider='Bailian', name='qwen3-coder-plus', alias='qwen3-coder-plus',
         context_size=1000000, input_size=997952, output_size=65536,
         pricing_tiers=[
             dict(label='<32k', context_size=1000000, input_size=32768, output_size=65536,
                  input_price=4, output_price=16, cache_creation_price=0, cache_hit_price=0),
             dict(label='32k~128k', context_size=1000000, input_size=131072, output_size=65536,
                  input_price=6, output_price=24, cache_creation_price=0, cache_hit_price=0),
             dict(label='128k~256k', context_size=1000000, input_size=262144, output_size=65536,
                  input_price=10, output_price=40, cache_creation_price=0, cache_hit_price=0),
             dict(label='256k~1M', context_size=1000000, input_size=997952, output_size=65536,
                  input_price=20, output_price=200, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=4, output_price=16, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Qwen VL Max', provider='Bailian', name='qwen-vl-max', alias='qwen-vl-max',
         context_size=32768, input_size=32768, output_size=4096, pricing_tiers=None,
         input_price=3, output_price=9, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=True, support_audio=False, support_video=True,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False),
    dict(label='Kimi K2.5 (Bailian)', provider='Bailian', name='kimi-k2.5', alias='kimi-k2.5-bailian',
         context_size=262144, input_size=260096, output_size=98304, pricing_tiers=None,
         input_price=4, output_price=21, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Kimi K2.5 Long (Proxy)', provider='Bailian', name='kimi/kimi-k2.5', alias='kimi-k2.5-long',
         context_size=262144, input_size=262144, output_size=262144, pricing_tiers=None,
         input_price=4, output_price=21, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='DeepSeek R1 (Bailian)', provider='Bailian', name='deepseek-r1', alias='deepseek-r1-bailian',
         context_size=64000, input_size=64000, output_size=8192, pricing_tiers=None,
         input_price=4, output_price=16, cache_creation_price=0, cache_hit_price=1,
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='text-embedding-v4', provider='Bailian', name='text-embedding-v4', alias='text-embedding-v4',
         context_size=8192, input_size=8192, output_size=1536, pricing_tiers=None,
         input_price=0.5, output_price=0, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=True),
    dict(label='text-embedding-v3', provider='Bailian', name='text-embedding-v3', alias='text-embedding-v3',
         context_size=8192, input_size=8192, output_size=1536, pricing_tiers=None,
         input_price=0.5, output_price=0, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=True),
    # ── Bailian / Qwen Image ─────────────────────────────────────────────────
    # Qwen image generation models — flat per-image pricing (CNY).
    dict(
        label='Qwen Image 2.0 Pro',
        provider='Bailian',
        name='qwen-image-2.0-pro',
        alias='qwen-image-2.0-pro',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.5,
                'tiers': [
                    {'resolution': '1K', 'price': 0.5},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Qwen Image 2.0',
        provider='Bailian',
        name='qwen-image-2.0',
        alias='qwen-image-2.0',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.2,
                'tiers': [
                    {'resolution': '1K', 'price': 0.2},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # ── MiniMax ──────────────────────────────────────────────────────────────
    dict(label='MiniMax M2.5', provider='Bailian', name='MiniMax-M2.5', alias='MiniMax-M2.5',
         context_size=196608, input_size=196601, output_size=32768, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.1', provider='Bailian', name='MiniMax-M2.1', alias='MiniMax-M2.1',
         context_size=204800, input_size=172032, output_size=32768, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.7 (Proxy)', provider='Bailian', name='MiniMax/MiniMax-M2.7', alias='MiniMax-M2.7',
         context_size=204800, input_size=204800, output_size=131072, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.5 (Proxy)', provider='Bailian', name='MiniMax/MiniMax-M2.5', alias='MiniMax-M2.5',
         context_size=204800, input_size=204800, output_size=131072, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.1 (Proxy)', provider='Bailian', name='MiniMax/MiniMax-M2.1', alias='MiniMax-M2.1',
         context_size=204800, input_size=204800, output_size=131072, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         support_kvcache=False, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.7', provider='MiniMax', name='MiniMax-M2.7', alias='MiniMax-M2.7',
         context_size=204800, input_size=204800, output_size=65536, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=2.625, cache_hit_price=0.42,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.7 Highspeed', provider='MiniMax', name='MiniMax-M2.7-highspeed', alias='MiniMax-M2.7-Highspeed',
         context_size=204800, input_size=204800, output_size=65536, pricing_tiers=None,
         input_price=4.2, output_price=16.8, cache_creation_price=2.625, cache_hit_price=0.42,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.5', provider='MiniMax', name='MiniMax-M2.5', alias='MiniMax-M2.5',
         context_size=204800, input_size=204800, output_size=65536, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=2.625, cache_hit_price=0.42,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.5 Highspeed', provider='MiniMax', name='MiniMax-M2.5-highspeed', alias='MiniMax-M2.5-Highspeed',
         context_size=204800, input_size=204800, output_size=65536, pricing_tiers=None,
         input_price=4.2, output_price=16.8, cache_creation_price=2.625, cache_hit_price=0.42,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.1', provider='MiniMax', name='MiniMax-M2.1', alias='MiniMax-M2.1',
         context_size=204800, input_size=204800, output_size=65536, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=2.625, cache_hit_price=0.21,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2.1 Highspeed', provider='MiniMax', name='MiniMax-M2.1-highspeed', alias='MiniMax-M2.1-Highspeed',
         context_size=204800, input_size=204800, output_size=65536, pricing_tiers=None,
         input_price=4.2, output_price=16.8, cache_creation_price=2.625, cache_hit_price=0.21,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='MiniMax M2', provider='MiniMax', name='MiniMax-M2', alias='MiniMax-M2',
         context_size=204800, input_size=204800, output_size=65536, pricing_tiers=None,
         input_price=2.1, output_price=8.4, cache_creation_price=2.625, cache_hit_price=0.21,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=False, support_online_video=False, support_embedding=False),
    # ── Volcengine Doubao ────────────────────────────────────────────────────
    dict(label='Doubao-seed-2-0-pro-260215', provider='Volcengine', name='doubao-seed-2-0-pro-260215', alias='doubao-seed-2.0-pro',
         context_size=262144, input_size=262144, output_size=262144,
         pricing_tiers=[
             dict(label='0~32k', context_size=262144, input_size=32768, output_size=262144,
                  input_price=3.2, output_price=16, cache_creation_price=0, cache_hit_price=0.64),
             dict(label='32k~128k', context_size=262144, input_size=131072, output_size=262144,
                  input_price=4.8, output_price=24, cache_creation_price=0, cache_hit_price=0.96),
             dict(label='128k~256k', context_size=262144, input_size=262144, output_size=262144,
                  input_price=9.6, output_price=48, cache_creation_price=0, cache_hit_price=1.92),
         ],
         input_price=3.2, output_price=16, cache_creation_price=0, cache_hit_price=0.64,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Doubao-seed-2-0-lite-260215', provider='Volcengine', name='doubao-seed-2-0-lite-260215', alias='doubao-seed-2.0-lite',
         context_size=262144, input_size=262144, output_size=262144,
         pricing_tiers=[
             dict(label='0~32k', context_size=262144, input_size=32768, output_size=262144,
                  input_price=0.6, output_price=3.6, cache_creation_price=0, cache_hit_price=0.12),
             dict(label='32k~128k', context_size=262144, input_size=131072, output_size=262144,
                  input_price=0.9, output_price=5.4, cache_creation_price=0, cache_hit_price=0.18),
             dict(label='128k~256k', context_size=262144, input_size=262144, output_size=262144,
                  input_price=1.8, output_price=10.8, cache_creation_price=0, cache_hit_price=0.36),
         ],
         input_price=0.6, output_price=3.6, cache_creation_price=0, cache_hit_price=0.12,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Doubao-seed-2-0-mini-260215', provider='Volcengine', name='doubao-seed-2-0-mini-260215', alias='doubao-seed-2.0-mini',
         context_size=262144, input_size=262144, output_size=262144,
         pricing_tiers=[
             dict(label='0~32k', context_size=262144, input_size=32768, output_size=262144,
                  input_price=0.2, output_price=2.0, cache_creation_price=0, cache_hit_price=0.04),
             dict(label='32k~128k', context_size=262144, input_size=131072, output_size=262144,
                  input_price=0.4, output_price=4, cache_creation_price=0, cache_hit_price=0.08),
             dict(label='128k~256k', context_size=262144, input_size=262144, output_size=262144,
                  input_price=0.8, output_price=8, cache_creation_price=0, cache_hit_price=0.16),
         ],
         input_price=0.2, output_price=2.0, cache_creation_price=0, cache_hit_price=0.04,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Doubao-seed-1-8-251228', provider='Volcengine', name='doubao-seed-1-8-251228', alias='doubao-seed-1.8',
         context_size=262144, input_size=262144, output_size=262144,
         pricing_tiers=[
             dict(label='0~32k', context_size=262144, input_size=32768, output_size=262144,
                  input_price=0.8, output_price=2.0, cache_creation_price=0, cache_hit_price=0.16),
             dict(label='32k~128k', context_size=262144, input_size=131072, output_size=262144,
                  input_price=1.2, output_price=16, cache_creation_price=0, cache_hit_price=0.16),
             dict(label='128k~256k', context_size=262144, input_size=262144, output_size=262144,
                  input_price=2.4, output_price=24, cache_creation_price=0, cache_hit_price=0.16),
         ],
         input_price=0.8, output_price=2.0, cache_creation_price=0, cache_hit_price=0.16,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Doubao-seed-2-0-code-preview-260215', provider='Volcengine', name='doubao-seed-2-0-code-preview-260215', alias='doubao-seed-2.0-code-preview',
         context_size=262144, input_size=262144, output_size=262144,
         pricing_tiers=[
             dict(label='0~32k', context_size=262144, input_size=32768, output_size=262144,
                  input_price=3.2, output_price=16, cache_creation_price=0, cache_hit_price=0.64),
             dict(label='32k~128k', context_size=262144, input_size=131072, output_size=262144,
                  input_price=4.8, output_price=24, cache_creation_price=0, cache_hit_price=0.96),
             dict(label='128k~256k', context_size=262144, input_size=262144, output_size=262144,
                  input_price=9.6, output_price=48, cache_creation_price=0, cache_hit_price=1.92),
         ],
         input_price=3.2, output_price=16, cache_creation_price=0, cache_hit_price=0.64,
         currency='CNY',
         support_kvcache=True, support_image=False, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    # ── TencentVOD Gemini Image Models ──────────────────────────────────────
    # Image pricing uses output_pricing with per_image type and resolution tiers.
    # Prices are per image, calculated based on resolution tier (512, 1K, 2K, 3K, 4K).
    # supported_image_formats lists every valid WxH for easy reference.
    # GG 2.5 — single resolution per aspect ratio, no quality tier
    dict(
        label='Gemini 2.5 Flash Image (TencentVOD)',
        provider='TencentVOD',
        name='gemini-2.5-flash-image',
        alias='gemini-2.5-flash-image',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats='1024x1024,832x1248,1248x832,864x1184,1184x864,896x1152,1152x896,768x1344,1344x768,1536x672',
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.3,
                'tiers': [
                    {'resolution': '512', 'price': 0.3},
                    {'resolution': '1K', 'price': 0.3},
                    {'resolution': '2K', 'price': 0.3},
                    {'resolution': '4K', 'price': 0.3},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # GG 3.0 — three tiers: 1K / 2K / 4K
    dict(
        label='Gemini 3 Pro Image Preview (TencentVOD)',
        provider='TencentVOD',
        name='gemini-3-pro-image-preview',
        alias='gemini-3-pro-image-preview',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '1024x1024,2048x2048,4096x4096,'
            '848x1264,1696x2528,3392x5056,'
            '1264x848,2528x1696,5056x3392,'
            '896x1200,1792x2400,3584x4800,'
            '1200x896,2400x1792,4800x3584,'
            '928x1152,1856x2304,3712x4608,'
            '1152x928,2304x1856,4608x3712,'
            '768x1376,1536x2752,3072x5504,'
            '1376x768,2752x1536,5504x3072,'
            '1584x672,3168x1344,6336x2688'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 1,
                'tiers': [
                    {'resolution': '512', 'price': 1},
                    {'resolution': '1K', 'price': 1},
                    {'resolution': '2K', 'price': 1},
                    {'resolution': '4K', 'price': 1.8},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # GG 3.1 — four tiers: 512 / 1K / 2K / 4K (14 aspect ratios)
    dict(
        label='Gemini 3.1 Flash Image Preview (TencentVOD)',
        provider='TencentVOD',
        name='gemini-3.1-flash-image-preview',
        alias='gemini-3.1-flash-image-preview',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '512x512,1024x1024,2048x2048,4096x4096,'
            '256x1024,512x2048,1024x4096,2048x8192,'
            '192x1536,384x3072,768x6144,1536x12288,'
            '424x632,848x1264,1696x2528,3392x5056,'
            '632x424,1264x848,2528x1696,5056x3392,'
            '448x600,896x1200,1792x2400,3584x4800,'
            '1024x256,2048x512,4096x1024,8192x2048,'
            '600x448,1200x896,2400x1792,4800x3584,'
            '464x576,928x1152,1856x2304,3712x4608,'
            '576x464,1152x928,2304x1856,4608x3712,'
            '1536x192,3072x384,6144x768,12288x1536,'
            '384x688,768x1376,1536x2752,3072x5504,'
            '688x384,1376x768,2752x1536,5504x3072,'
            '792x168,1584x672,3168x1344,6336x2688'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.5,
                'tiers': [
                    {'resolution': '512', 'price': 0.5},
                    {'resolution': '1K', 'price': 0.5},
                    {'resolution': '2K', 'price': 0.75},
                    {'resolution': '4K', 'price': 1.12},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # ── TencentVOD Kling Video Models ───────────────────────────────────────
    # Kling v3 Omni — video generation with per-second pricing.
    # Pricing varies by resolution × audio × reference_video (16 tiers).
    # Prices are in CNY per second.
    dict(
        label='Kling V3 Omni (TencentVOD)',
        provider='TencentVOD',
        name='kling-v3-omni',
        alias='kling-v3-omni',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 0.6,
                'tiers': [
                    # ── No audio, No reference video ──
                    {'resolution': '720p',  'audio': False, 'reference_video': False, 'price': 0.6},
                    {'resolution': '1080p', 'audio': False, 'reference_video': False, 'price': 0.8},
                    {'resolution': '2K',    'audio': False, 'reference_video': False, 'price': 1.0},
                    {'resolution': '4K',    'audio': False, 'reference_video': False, 'price': 1.2},
                    # ── Audio, No reference video ──
                    {'resolution': '720p',  'audio': True,  'reference_video': False, 'price': 0.8},
                    {'resolution': '1080p', 'audio': True,  'reference_video': False, 'price': 1.0},
                    {'resolution': '2K',    'audio': True,  'reference_video': False, 'price': 1.2},
                    {'resolution': '4K',    'audio': True,  'reference_video': False, 'price': 1.5},
                    # ── No audio, Reference video ──
                    {'resolution': '720p',  'audio': False, 'reference_video': True,  'price': 0.9},
                    {'resolution': '1080p', 'audio': False, 'reference_video': True,  'price': 1.2},
                    {'resolution': '2K',    'audio': False, 'reference_video': True,  'price': 1.5},
                    {'resolution': '4K',    'audio': False, 'reference_video': True,  'price': 2.0},
                    # ── Audio + Reference video ──
                    {'resolution': '720p',  'audio': True,  'reference_video': True,  'price': 1.1},
                    {'resolution': '1080p', 'audio': True,  'reference_video': True,  'price': 1.4},
                    {'resolution': '2K',    'audio': True,  'reference_video': True,  'price': 1.8},
                    {'resolution': '4K',    'audio': True,  'reference_video': True,  'price': 2.4},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=False, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # ── Volcengine Seedream Image Models ──────────────────────────────────────
    # Seedream models support resolution tiers: 1K / 2K / 3K / 4K
    dict(
        label='Seedream 4.0 (Volcengine)',
        provider='Volcengine',
        name='seedream-4.0',
        alias='seedream-4.0',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '1024x1024,864x1152,1152x864,1312x736,736x1312,832x1248,1248x832,1568x672,'
            '2048x2048,1728x2304,2304x1728,2848x1600,1600x2848,2496x1664,1664x2496,3136x1344,'
            '4096x4096,3520x4704,4704x3520,5504x3040,3040x5504,3328x4992,4992x3328,6240x2656'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0,
                'tiers': [
                    {'resolution': '1K', 'price': 0},
                    {'resolution': '2K', 'price': 0},
                    {'resolution': '4K', 'price': 0},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Seedream 4.5 (Volcengine)',
        provider='Volcengine',
        name='seedream-4.5',
        alias='seedream-4.5',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '2048x2048,1728x2304,2304x1728,2848x1600,1600x2848,2496x1664,1664x2496,3136x1344,'
            '4096x4096,3520x4704,4704x3520,5504x3040,3040x5504,3328x4992,4992x3328,6240x2656'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0,
                'tiers': [
                    {'resolution': '2K', 'price': 0},
                    {'resolution': '4K', 'price': 0},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Seedream 5.0 Lite (Volcengine)',
        provider='Volcengine',
        name='seedream-5.0-lite',
        alias='seedream-5.0-lite',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '2048x2048,1728x2304,2304x1728,2848x1600,1600x2848,2496x1664,1664x2496,3136x1344,'
            '3072x3072,2592x3456,3456x2592,4096x2304,2304x4096,2496x3744,3744x2496,4704x2016'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0,
                'tiers': [
                    {'resolution': '2K', 'price': 0},
                    {'resolution': '3K', 'price': 0},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
]


def seed_builtin_templates():
    """
    Insert or update built-in templates in the database.

    This function is idempotent: each template is inserted if the
    (provider, label) pair does not already exist, or updated if it does.
    The same model name may appear multiple times across different providers
    or with different labels, so name alone is not a reliable uniqueness key.
    """
    existing = {
        (row.provider, row.label): row
        for row in db.session.query(ModelTemplate).all()
    }
    for tpl in BUILTIN_TEMPLATES:
        key = (tpl['provider'], tpl['label'])
        if key not in existing:
            db.session.add(ModelTemplate(**tpl))
        else:
            # Update existing template with latest built-in data
            db_tpl = existing[key]
            for field, value in tpl.items():
                if field not in ('provider', 'label'):
                    setattr(db_tpl, field, value)
    db.session.commit()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@model_templates_bp.route('/model-templates/', methods=['GET'])
@token_required
def list_model_templates(current_user):
    """List all model templates."""
    templates = db.session.query(ModelTemplate).order_by(
        ModelTemplate.provider, ModelTemplate.id
    ).all()
    return jsonify([t.to_dict() for t in templates])


@model_templates_bp.route('/model-templates/', methods=['POST'])
@token_required
def create_model_template(current_user):
    """Create a custom model template."""
    data = request.get_json()
    if not data.get('label') or not data.get('name') or not data.get('provider'):
        return jsonify({'detail': 'label, name and provider are required'}), 400

    # Parse retirement_time if provided as ISO string
    retirement_time = None
    if data.get('retirement_time'):
        try:
            retirement_time = datetime.fromisoformat(data['retirement_time'].replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return jsonify({'detail': 'Invalid retirement_time format. Use ISO 8601 (e.g. 2025-01-01T00:00:00)'}), 400

    tpl = ModelTemplate(
        label=data['label'],
        provider=data['provider'],
        name=data['name'],
        alias=data.get('alias'),
        context_size=data.get('context_size', 4096),
        input_size=data.get('input_size', 4096),
        output_size=data.get('output_size', 4096),
        reasoning_effort=data.get('reasoning_effort') or None,
        supported_image_formats=data.get('supported_image_formats') or None,
        pricing_tiers=data.get('pricing_tiers') or None,
        input_price=data.get('input_price', 0.0),
        output_price=data.get('output_price', 0.0),
        cache_creation_price=data.get('cache_creation_price', 0.0),
        cache_hit_price=data.get('cache_hit_price', 0.0),
        currency=data.get('currency') or 'USD',
        retirement_time=retirement_time,
        rpm=data.get('rpm') or None,
        tpm=data.get('tpm') or None,
        discount=data.get('discount') if data.get('discount') is not None else 1.0,
        support_kvcache=data.get('support_kvcache', False),
        support_image=data.get('support_image', False),
        support_audio=data.get('support_audio', False),
        support_video=data.get('support_video', False),
        support_file=data.get('support_file', False),
        support_web_search=data.get('support_web_search', False),
        support_tool_search=data.get('support_tool_search', False),
        support_thinking=data.get('support_thinking', False),
        support_online_image=data.get('support_online_image', False),
        support_online_video=data.get('support_online_video', False),
        support_embedding=data.get('support_embedding', False),
    )
    db.session.add(tpl)
    db.session.commit()
    db.session.refresh(tpl)
    return jsonify(tpl.to_dict()), 201


@model_templates_bp.route('/model-templates/<int:template_id>', methods=['PUT'])
@token_required
def update_model_template(current_user, template_id):
    """Update a model template."""
    tpl = db.session.query(ModelTemplate).filter(ModelTemplate.id == template_id).first()
    if not tpl:
        return jsonify({'detail': 'Template not found'}), 404

    data = request.get_json()
    for field in [
        'label', 'provider', 'name', 'alias', 'context_size', 'input_size', 'output_size',
        'input_price', 'output_price', 'cache_creation_price', 'cache_hit_price',
        'currency', 'rpm', 'tpm', 'discount',
        'support_kvcache', 'support_image', 'support_audio', 'support_video',
        'support_file', 'support_web_search', 'support_tool_search', 'support_thinking',
        'support_online_image', 'support_online_video', 'support_embedding',
        'output_size', 'reasoning_effort', 'supported_image_formats', 'pricing_tiers',
    ]:
        if field in data:
            setattr(tpl, field, data[field])

    # Handle retirement_time separately (ISO string → datetime)
    if 'retirement_time' in data:
        rt = data['retirement_time']
        if rt:
            try:
                tpl.retirement_time = datetime.fromisoformat(rt.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                return jsonify({'detail': 'Invalid retirement_time format. Use ISO 8601 (e.g. 2025-01-01T00:00:00)'}), 400
        else:
            tpl.retirement_time = None

    # Normalise nullable string fields
    if tpl.reasoning_effort == '':
        tpl.reasoning_effort = None
    if tpl.supported_image_formats == '':
        tpl.supported_image_formats = None
    if not tpl.currency:
        tpl.currency = 'USD'

    db.session.commit()
    db.session.refresh(tpl)
    return jsonify(tpl.to_dict())


@model_templates_bp.route('/model-templates/<int:template_id>', methods=['DELETE'])
@token_required
def delete_model_template(current_user, template_id):
    """Delete a model template."""
    tpl = db.session.query(ModelTemplate).filter(ModelTemplate.id == template_id).first()
    if not tpl:
        return jsonify({'detail': 'Template not found'}), 404

    db.session.delete(tpl)
    db.session.commit()
    return '', 204


@model_templates_bp.route('/model-templates/seed', methods=['POST'])
@token_required
def reseed_model_templates(current_user):
    """
    Re-seed built-in templates.
    Inserts missing built-ins and updates existing ones with latest data.
    """
    existing = {
        (row.provider, row.label): row
        for row in db.session.query(ModelTemplate).all()
    }
    added = 0
    updated = 0
    for tpl in BUILTIN_TEMPLATES:
        key = (tpl['provider'], tpl['label'])
        if key not in existing:
            db.session.add(ModelTemplate(**tpl))
            added += 1
        else:
            db_tpl = existing[key]
            for field, value in tpl.items():
                if field not in ('provider', 'label'):
                    setattr(db_tpl, field, value)
            updated += 1
    db.session.commit()
    return jsonify({'added': added, 'updated': updated})
