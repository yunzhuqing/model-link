"""
Built-in model template seed data, organized by provider.
"""
from app.data.openai_templates import OPENAI_TEMPLATES
from app.data.azure_templates import AZURE_TEMPLATES
from app.data.anthropic_templates import ANTHROPIC_TEMPLATES
from app.data.google_templates import GOOGLE_TEMPLATES
from app.data.vertexai_templates import VERTEXAI_TEMPLATES
from app.data.deepseek_templates import DEEPSEEK_TEMPLATES
from app.data.moonshot_templates import MOONSHOT_TEMPLATES
from app.data.glm_templates import GLM_TEMPLATES
from app.data.bailian_templates import BAILIAN_TEMPLATES
from app.data.minimax_templates import MINIMAX_TEMPLATES
from app.data.volcengine_templates import VOLCENGINE_TEMPLATES
from app.data.byteplus_templates import BYTEPLUS_TEMPLATES
from app.data.tencentvod_templates import TENCENTVOD_TEMPLATES

BUILTIN_TEMPLATES = (
    OPENAI_TEMPLATES
    + AZURE_TEMPLATES
    + ANTHROPIC_TEMPLATES
    + GOOGLE_TEMPLATES
    + VERTEXAI_TEMPLATES
    + DEEPSEEK_TEMPLATES
    + MOONSHOT_TEMPLATES
    + GLM_TEMPLATES
    + BAILIAN_TEMPLATES
    + MINIMAX_TEMPLATES
    + VOLCENGINE_TEMPLATES
    + BYTEPLUS_TEMPLATES
    + TENCENTVOD_TEMPLATES
)
