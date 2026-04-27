"""TencentVOD model templates — chat (GPT, Gemini), image (Gemini), video (Kling)."""

TENCENTVOD_TEMPLATES = [
    # ── TencentVOD Chat Models (CNY pricing) ────────────────────────────────
    # GPT-5.4 — tiered by context size
    dict(label='GPT-5.4 (TencentVOD)', provider='TencentVOD', name='gpt-5.4', alias='gpt-5.4',
         context_size=272000, input_size=272000, output_size=8192,
         pricing_tiers=[
             dict(label='≤272k ctx', context_size=272000, input_size=272000, output_size=8192,
                  input_price=18.75, output_price=112.5, cache_creation_price=0, cache_hit_price=1.88),
             dict(label='>272k ctx', context_size=1000000, input_size=1000000, output_size=8192,
                  input_price=37.5, output_price=168.75, cache_creation_price=0, cache_hit_price=3.75),
         ],
         input_price=18.75, output_price=112.5, cache_creation_price=0, cache_hit_price=1.88,
         currency='CNY',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=True,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    # GPT-5.4 Pro — tiered by context size
    dict(label='GPT-5.4 Pro (TencentVOD)', provider='TencentVOD', name='gpt-5.4-pro', alias='gpt-5.4-pro',
         context_size=272000, input_size=272000, output_size=8192,
         pricing_tiers=[
             dict(label='≤272k ctx', context_size=272000, input_size=272000, output_size=8192,
                  input_price=225, output_price=1350, cache_creation_price=0, cache_hit_price=0),
             dict(label='>272k ctx', context_size=1000000, input_size=1000000, output_size=8192,
                  input_price=450, output_price=2025, cache_creation_price=0, cache_hit_price=0),
         ],
         input_price=225, output_price=1350, cache_creation_price=0, cache_hit_price=0,
         currency='CNY',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=True,
         support_thinking=True, support_online_image=True, support_online_video=False, support_embedding=False),
    # GPT-5.2 — flat pricing
    dict(label='GPT-5.2 (TencentVOD)', provider='TencentVOD', name='gpt-5.2', alias='gpt-5.2',
         context_size=272000, input_size=272000, output_size=8192, pricing_tiers=None,
         input_price=12.25, output_price=98, cache_creation_price=0, cache_hit_price=1.22,
         currency='CNY',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    # GPT-5.1 — flat pricing
    dict(label='GPT-5.1 (TencentVOD)', provider='TencentVOD', name='gpt-5.1', alias='gpt-5.1',
         context_size=128000, input_size=128000, output_size=8192, pricing_tiers=None,
         input_price=8.75, output_price=70, cache_creation_price=0, cache_hit_price=0.87,
         currency='CNY',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=False, support_video=False,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=False, support_embedding=False),
    # Gemini 3.1 Pro Preview — tiered by context size
    dict(label='Gemini 3.1 Pro Preview (TencentVOD)', provider='TencentVOD', name='gemini-3.1-pro-preview', alias='gemini-3.1-pro-preview',
         context_size=1048576, input_size=1048576, output_size=65536,
         pricing_tiers=[
             dict(label='≤200k ctx', context_size=1048576, input_size=204800, output_size=65536,
                  input_price=15, output_price=90, cache_creation_price=0, cache_hit_price=1.5),
             dict(label='>200k ctx', context_size=1048576, input_size=1048576, output_size=65536,
                  input_price=30, output_price=135, cache_creation_price=0, cache_hit_price=3),
         ],
         input_price=15, output_price=90, cache_creation_price=0, cache_hit_price=1.5,
         currency='CNY',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=True, support_embedding=False),
    # Gemini 3 Flash Preview — tiered by audio input
    dict(label='Gemini 3 Flash Preview (TencentVOD)', provider='TencentVOD', name='gemini-3-flash-preview', alias='gemini-3-flash-preview',
         context_size=1048576, input_size=1048576, output_size=65536,
         pricing_tiers=[
             dict(label='without audio input', context_size=1048576, input_size=1048576, output_size=65536,
                  input_price=3.5, output_price=21, cache_creation_price=0, cache_hit_price=0.35),
             dict(label='with audio input', context_size=1048576, input_size=1048576, output_size=65536,
                  input_price=7, output_price=21, cache_creation_price=0, cache_hit_price=0.7),
         ],
         input_price=3.5, output_price=21, cache_creation_price=0, cache_hit_price=0.35,
         currency='CNY',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False),
    # Gemini 2.5 Pro — tiered by context size
    dict(label='Gemini 2.5 Pro (TencentVOD)', provider='TencentVOD', name='gemini-2.5-pro-preview-03-25', alias='gemini-2.5-pro',
         context_size=1048576, input_size=1048576, output_size=8192,
         pricing_tiers=[
             dict(label='≤200k ctx', context_size=1048576, input_size=204800, output_size=8192,
                  input_price=9.37, output_price=75, cache_creation_price=0, cache_hit_price=0.93),
             dict(label='>200k ctx', context_size=1048576, input_size=1048576, output_size=8192,
                  input_price=18.75, output_price=112.5, cache_creation_price=0, cache_hit_price=1.87),
         ],
         input_price=9.37, output_price=75, cache_creation_price=0, cache_hit_price=0.93,
         currency='CNY',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=True, support_online_image=True, support_online_video=True, support_embedding=False),
    # Gemini 2.5 Flash — tiered by audio input
    dict(label='Gemini 2.5 Flash (TencentVOD)', provider='TencentVOD', name='gemini-2.5-flash-preview-05-20', alias='gemini-2.5-flash',
         context_size=1048576, input_size=1048576, output_size=8192,
         pricing_tiers=[
             dict(label='without audio input', context_size=1048576, input_size=1048576, output_size=8192,
                  input_price=2.25, output_price=18.75, cache_creation_price=0, cache_hit_price=0.22),
             dict(label='with audio input', context_size=1048576, input_size=1048576, output_size=8192,
                  input_price=7.5, output_price=18.75, cache_creation_price=0, cache_hit_price=0.75),
         ],
         input_price=2.25, output_price=18.75, cache_creation_price=0, cache_hit_price=0.22,
         currency='CNY',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=True, support_video=True,
         support_file=True, support_web_search=True, support_tool_search=False,
         support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False),

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
        timeout=600,
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
        timeout=600,
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
        timeout=600,
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # ── TencentVOD GPT Image 2 (OG) ─────────────────────────────────────────
    # GPT Image 2 — quality-dependent pricing (low/medium/high).
    # ModelName=OG, ModelVersion determined by quality parameter:
    #   quality=low|auto  → image2_low
    #   quality=medium    → image2_medium
    #   quality=high      → image2_high
    # Pricing varies by quality × resolution tier (1K / 2K / 4K).
    # Supported AspectRatios: 1:1, 3:2, 2:3, 3:4, 4:3, 16:9, 9:16, 21:9, 9:21.
    dict(
        label='GPT Image 2 (TencentVOD)',
        provider='TencentVOD',
        name='gpt-image-2',
        alias='gpt-image-2',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '1024x1024,2048x2048,3840x3840,'
            '1536x1024,3072x2048,3840x2560,'
            '1024x1536,2048x3072,2560x3840,'
            '768x1024,1536x2048,2880x3840,'
            '1024x768,2048x1536,3840x2880,'
            '1024x576,2048x1152,3840x2160,'
            '576x1024,1152x2048,2160x3840,'
            '1024x439,2048x878,3840x1646,'
            '439x1024,878x2048,1646x3840'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.3,
                'tiers': [
                    # ── quality=low (image2_low) ──
                    {'resolution': '1K', 'quality': 'low', 'price': 0.3},
                    {'resolution': '2K', 'quality': 'low', 'price': 0.338},
                    {'resolution': '4K', 'quality': 'low', 'price': 0.398},
                    # ── quality=medium (image2_medium) ──
                    {'resolution': '1K', 'quality': 'medium', 'price': 0.638},
                    {'resolution': '2K', 'quality': 'medium', 'price': 1.05},
                    {'resolution': '4K', 'quality': 'medium', 'price': 1.583},
                    # ── quality=high (image2_high) ──
                    {'resolution': '1K', 'quality': 'high', 'price': 1.838},
                    {'resolution': '2K', 'quality': 'high', 'price': 3.45},
                    {'resolution': '4K', 'quality': 'high', 'price': 5.588},
                ],
            },
        },
        input_price=0, output_price=0, cache_creation_price=0, cache_hit_price=0,
        currency='CNY',
        timeout=600,
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
        timeout=900,
        support_kvcache=False, support_image=False, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
]
