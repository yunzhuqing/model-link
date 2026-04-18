"""DeepSeek model templates."""

DEEPSEEK_TEMPLATES = [
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
]
