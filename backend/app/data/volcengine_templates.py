"""Volcengine Doubao chat models + Seedream image models."""

VOLCENGINE_TEMPLATES = [
    # ── Volcengine Doubao Chat Models ────────────────────────────────────────
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
