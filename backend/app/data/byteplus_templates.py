"""BytePlus Seed chat models + Seedream image + Seedance video models.

BytePlus is the international version of Volcengine (ByteDance).
Model names differ from the domestic version (no 'doubao-' prefix).
All prices are in USD per million tokens (or per image/video token).

API endpoint: https://ark.ap-southeast.bytepluses.com/api/v3
"""

BYTEPLUS_TEMPLATES = [
    # ── BytePlus Seed Chat Models ──────────────────────────────────────────
    dict(label='Seed-2-0-pro-260328 (BytePlus)', provider='BytePlus', name='seed-2-0-pro-260328', alias='seed-2.0-pro',
         context_size=256000, input_size=256000, output_size=128000,
         pricing_tiers=[
             dict(label='0~128k', context_size=256000, input_size=128000, output_size=128000,
                  input_price=0.5, output_price=3, cache_creation_price=0, cache_hit_price=0.1),
             dict(label='128k~256k', context_size=256000, input_size=256000, output_size=128000,
                  input_price=1, output_price=6, cache_creation_price=0, cache_hit_price=0.2),
         ],
         input_price=0.5, output_price=3, cache_creation_price=0, cache_hit_price=0.1,
         currency='USD',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=False, support_video=True,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Seed-2-0-lite-260228 (BytePlus)', provider='BytePlus', name='seed-2-0-lite-260228', alias='seed-2.0-lite',
         context_size=256000, input_size=256000, output_size=128000,
         pricing_tiers=[
             dict(label='0~128k', context_size=256000, input_size=128000, output_size=128000,
                  input_price=0.25, output_price=2, cache_creation_price=0, cache_hit_price=0.05),
             dict(label='128k~256k', context_size=256000, input_size=256000, output_size=128000,
                  input_price=0.5, output_price=4, cache_creation_price=0, cache_hit_price=0.1),
         ],
         input_price=0.25, output_price=2, cache_creation_price=0, cache_hit_price=0.05,
         currency='USD',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=False, support_video=True,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Seed-2-0-mini-260215 (BytePlus)', provider='BytePlus', name='seed-2-0-mini-260215', alias='seed-2.0-mini',
         context_size=256000, input_size=256000, output_size=128000,
         pricing_tiers=[
             dict(label='0~128k', context_size=256000, input_size=128000, output_size=128000,
                  input_price=0.1, output_price=0.4, cache_creation_price=0, cache_hit_price=0.02),
             dict(label='128k~256k', context_size=256000, input_size=256000, output_size=128000,
                  input_price=0.2, output_price=0.8, cache_creation_price=0, cache_hit_price=0.04),
         ],
         input_price=0.1, output_price=0.4, cache_creation_price=0, cache_hit_price=0.02,
         currency='USD',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=False, support_video=True,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    dict(label='Seed-2-0-code-preview-260328 (BytePlus)', provider='BytePlus', name='seed-2-0-code-preview-260328', alias='seed-2.0-code-preview',
         context_size=256000, input_size=256000, output_size=128000,
         pricing_tiers=[
             dict(label='0~128k', context_size=256000, input_size=128000, output_size=128000,
                  input_price=0.5, output_price=3, cache_creation_price=0, cache_hit_price=0.1),
             dict(label='128k~256k', context_size=256000, input_size=256000, output_size=128000,
                  input_price=1, output_price=6, cache_creation_price=0, cache_hit_price=0.2),
         ],
         input_price=0.5, output_price=3, cache_creation_price=0, cache_hit_price=0.1,
         currency='USD',
         timeout=300,
         support_kvcache=True, support_image=True, support_audio=False, support_video=True,
         support_file=False, support_web_search=False, support_tool_search=False,
         support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False),
    # ── BytePlus Seedream Image Models ────────────────────────────────────────
    dict(
        label='Seedream-5-0-260128 (BytePlus)',
        provider='BytePlus',
        name='seedream-5-0-260128',
        alias='seedream-5.0',
        context_size=4096, input_size=4096, output_size=1,
        supported_image_formats=(
            '2048x2048,1728x2304,2304x1728,2848x1600,1600x2848,2496x1664,1664x2496,3136x1344,'
            '3072x3072,2592x3456,3456x2592,4096x2304,2304x4096,2496x3744,3744x2496,4704x2016,'
            '4096x4096,3520x4704,4704x3520,5504x3040,3040x5504,3328x4992,4992x3328,6240x2656'
        ),
        pricing_tiers=None,
        output_pricing={
            'image': {
                'type': 'per_image',
                'price': 0.035,
                'tiers': [
                    {'resolution': 'default', 'price': 0.035},
                ],
            },
        },
        input_price=0, output_price=0.035, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        timeout=600,
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Seedream-4-5-251128 (BytePlus)',
        provider='BytePlus',
        name='seedream-4-5-251128',
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
                'price': 0.04,
                'tiers': [
                    {'resolution': 'default', 'price': 0.04},
                ],
            },
        },
        input_price=0, output_price=0.04, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        timeout=600,
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    dict(
        label='Seedream-4-0-250828 (BytePlus)',
        provider='BytePlus',
        name='seedream-4-0-250828',
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
                'price': 0.03,
                'tiers': [
                    {'resolution': 'default', 'price': 0.03},
                ],
            },
        },
        input_price=0, output_price=0.03, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        timeout=600,
        support_kvcache=False, support_image=True, support_audio=False, support_video=False,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=False, support_online_video=False, support_embedding=False,
    ),
    # ── BytePlus Seedance Video Models ────────────────────────────────────────
    dict(
        label='Seedance-1-5-pro-251215 (BytePlus)',
        provider='BytePlus',
        name='seedance-1-5-pro-251215',
        alias='seedance-1.5-pro',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_token',
                'price': 1.2,
                'tiers': [
                    # ── No audio ──
                    {'resolution': '480p',  'audio': False, 'price': 1.2},
                    {'resolution': '720p',  'audio': False, 'price': 1.2},
                    {'resolution': '1080p', 'audio': False, 'price': 1.2},
                    # ── With audio ──
                    {'resolution': '480p',  'audio': True,  'price': 2.4},
                    {'resolution': '720p',  'audio': True,  'price': 2.4},
                    {'resolution': '1080p', 'audio': True,  'price': 2.4},
                ],
            },
        },
        input_price=0, output_price=1.2, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        timeout=900,
        support_kvcache=False, support_image=True, support_audio=True, support_video=True,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False,
    ),
    dict(
        label='Dreamina-seedance-2-0-fast-260128 (BytePlus)',
        provider='BytePlus',
        name='dreamina-seedance-2-0-fast-260128',
        alias='dreamina-seedance-2.0-fast',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_token',
                'price': 3.3,
                'tiers': [
                    # ── Without video input ──
                    {'resolution': '480p',  'reference_video': False, 'price': 5.6},
                    {'resolution': '720p',  'reference_video': False, 'price': 5.6},
                    # ── With video input ──
                    {'resolution': '480p',  'reference_video': True,  'price': 3.3},
                    {'resolution': '720p',  'reference_video': True,  'price': 3.3},
                ],
            },
        },
        input_price=0, output_price=3.3, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        timeout=900,
        support_kvcache=False, support_image=True, support_audio=True, support_video=True,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False,
    ),
    dict(
        label='Dreamina-seedance-2-0-260128 (BytePlus)',
        provider='BytePlus',
        name='dreamina-seedance-2-0-260128',
        alias='dreamina-seedance-2.0',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_token',
                'price': 4.3,
                'tiers': [
                    # ── Without video input ──
                    {'resolution': '480p',  'reference_video': False, 'price': 7},
                    {'resolution': '720p',  'reference_video': False, 'price': 7},
                    {'resolution': '1080p', 'reference_video': False, 'price': 7.7},
                    # ── With video input ──
                    {'resolution': '480p',  'reference_video': True,  'price': 4.3},
                    {'resolution': '720p',  'reference_video': True,  'price': 4.3},
                    {'resolution': '1080p', 'reference_video': True,  'price': 4.7},
                ],
            },
        },
        input_price=0, output_price=4.3, cache_creation_price=0, cache_hit_price=0,
        currency='USD',
        timeout=900,
        support_kvcache=False, support_image=True, support_audio=True, support_video=True,
        support_file=False, support_web_search=False, support_tool_search=False,
        support_thinking=False, support_online_image=True, support_online_video=True, support_embedding=False,
    ),
]
