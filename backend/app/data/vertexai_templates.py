"""VertexAI model templates (Gemini chat, image, Veo video, Claude)."""

VERTEXAI_TEMPLATES = [
    # ── Claude (Anthropic on Vertex AI) ────────────────────────────────────
    dict(label='Claude Opus 4.7 (VertexAI)', provider='VertexAI', name='claude-opus-4-7', alias='claude-opus-4-7',
         context_size=1000000, input_size=1000000, output_size=128000, pricing_tiers=None,
         input_price=5, output_price=25, cache_creation_price=0, cache_5m_creation_price=3.75, cache_1h_creation_price=6.25, cache_hit_price=0.5,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=True, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='Claude Opus 4.6 (VertexAI)', provider='VertexAI', name='claude-opus-4-6', alias='claude-opus-4',
         context_size=1000000, input_size=1000000, output_size=128000, pricing_tiers=None,
         input_price=5, output_price=25, cache_creation_price=0, cache_5m_creation_price=3.75, cache_1h_creation_price=6.25, cache_hit_price=0.5,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=True, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='Claude Sonnet 4.6 (VertexAI)', provider='VertexAI', name='claude-sonnet-4-6', alias='claude-sonnet-4',
         context_size=1000000, input_size=1000000, output_size=128000, pricing_tiers=None,
         input_price=3, output_price=15, cache_creation_price=0, cache_5m_creation_price=2.25, cache_1h_creation_price=3.75, cache_hit_price=0.3,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=True, support_web_search=False, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    dict(label='Claude Haiku 4.5 (VertexAI)', provider='VertexAI', name='claude-haiku-4-5', alias='claude-haiku-4-5',
         context_size=200000, input_size=200000, output_size=8192, pricing_tiers=None,
         input_price=1, output_price=4, cache_creation_price=0, cache_5m_creation_price=0.80, cache_1h_creation_price=1.25, cache_hit_price=0.1,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=True, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    # ── Gemini Chat / Reasoning ────────────────────────────────────────────
    dict(label='Gemini 2.5 Pro (VertexAI)', provider='VertexAI', name='gemini-2.5-pro-preview-03-25', alias='gemini-2.5-pro',
         context_size=1048576, input_size=1048576, output_size=8192, pricing_tiers=None,
         input_price=1.25, output_price=10, cache_creation_price=0, cache_hit_price=0.31,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=True, support_embedding=False),
    dict(label='Gemini 3.1 Pro Preview (VertexAI)', provider='VertexAI', name='gemini-3.1-pro-preview', alias='gemini-3.1-pro-preview',
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
    dict(label='Gemini 3.1 Flash Lite (VertexAI)', provider='VertexAI', name='gemini-3.1-flash-lite', alias='gemini-3.1-flash-lite',
         context_size=1048576, input_size=1048576, output_size=65536, pricing_tiers=None,
         input_price=0.25, output_price=1.5, cache_creation_price=0, cache_hit_price=0.03,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False),
    dict(label='Gemini 3 Pro Preview (VertexAI)', provider='VertexAI', name='gemini-3-pro-preview', alias='gemini-3-pro-preview',
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
    dict(label='Gemini 3 Flash Preview (VertexAI)', provider='VertexAI', name='gemini-3-flash-preview', alias='gemini-3-flash-preview',
         context_size=1048576, input_size=1048576, output_size=65536, pricing_tiers=None,
         input_price=0.5, output_price=3, cache_creation_price=0, cache_hit_price=0.05,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False),
    # ── Gemini Image ──────────────────────────────────────────────────────
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
    # ── Veo Video Models ──────────────────────────────────────────────────
    dict(
        label='Veo 3.1 Generate (VertexAI)',
        provider='VertexAI',
        name='veo-3.1-generate-001',
        alias='veo-3.1-generate-001',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 0.4,
                'tiers': [
                    {'resolution': '720p',  'audio': True,  'price': 0.4},
                    {'resolution': '1080p', 'audio': True,  'price': 0.4},
                    {'resolution': '4K',    'audio': True,  'price': 0.6},
                    {'resolution': '720p',  'audio': False, 'price': 0.2},
                    {'resolution': '1080p', 'audio': False, 'price': 0.2},
                    {'resolution': '4K',    'audio': False, 'price': 0.4},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=False, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Veo 3.1 Fast Generate (VertexAI)',
        provider='VertexAI',
        name='veo-3.1-fast-generate-001',
        alias='veo-3.1-fast-generate-001',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 0.1,
                'tiers': [
                    {'resolution': '720p',  'audio': True,  'price': 0.1},
                    {'resolution': '1080p', 'audio': True,  'price': 0.12},
                    {'resolution': '4K',    'audio': True,  'price': 0.3},
                    {'resolution': '720p',  'audio': False, 'price': 0.08},
                    {'resolution': '1080p', 'audio': False, 'price': 0.1},
                    {'resolution': '4K',    'audio': False, 'price': 0.25},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=False, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Veo 3.1 Lite Generate (VertexAI)',
        provider='VertexAI',
        name='veo-3.1-lite-generate-001',
        alias='veo-3.1-lite-generate-001',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 0.05,
                'tiers': [
                    {'resolution': '720p',  'audio': True,  'price': 0.05},
                    {'resolution': '1080p', 'audio': True,  'price': 0.08},
                    {'resolution': '720p',  'audio': False, 'price': 0.03},
                    {'resolution': '1080p', 'audio': False, 'price': 0.05},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        support_kvcache=False, support_image=False, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
]
