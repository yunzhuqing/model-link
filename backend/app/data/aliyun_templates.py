"""Aliyun (yike) model templates — video generation models."""

ALIYUN_TEMPLATES = [
    dict(
        label='Aliyun Wonder-Pro (T2V/I2V)',
        provider='Aliyun',
        name='wonder-pro',
        alias='doubao-seedance-2.0',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 1.0,
                'tiers': [
                    {'resolution': '720P', 'price': 0.9},
                    {'resolution': '1080P', 'price': 1.2},
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
    dict(
        label='Aliyun Wonder-Standard (T2V/I2V)',
        provider='Aliyun',
        name='wonder-standard',
        alias='doubao-seedance-2.0-mini',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 0.8,
                'tiers': [
                    {'resolution': '720P', 'price': 0.7},
                    {'resolution': '1080P', 'price': 1.0},
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
    dict(
        label='Aliyun Wan3.0 Video',
        provider='Aliyun',
        name='wan3.0-video',
        alias='wan3.0-video',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 0.8,
                'tiers': [
                    {'resolution': '720P', 'price': 0.7},
                    {'resolution': '1080P', 'price': 1.0},
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
    dict(
        label='Aliyun Happyhorse 1.1',
        provider='Aliyun',
        name='happyhorse-1.1',
        alias='happyhorse-1.1',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 0.9,
                'tiers': [
                    {'resolution': '720P', 'price': 0.9},
                    {'resolution': '1080P', 'price': 1.2},
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
    dict(
        label='Aliyun Wan2.7',
        provider='Aliyun',
        name='wan2.7',
        alias='wan2.7',
        context_size=4096, input_size=4096, output_size=1,
        pricing_tiers=None,
        output_pricing={
            'video': {
                'type': 'per_second',
                'price': 0.8,
                'tiers': [
                    {'resolution': '720P', 'price': 0.7},
                    {'resolution': '1080P', 'price': 1.0},
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
