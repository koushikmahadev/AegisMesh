import os

# Default Vision API key configuration reading directly from system environment
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_API_KEY_FLOODNET = os.environ.get("OPENROUTER_API_KEY_FLOODNET", "")
OPENROUTER_API_KEY_3 = os.environ.get("OPENROUTER_API_KEY_3", "")
OPENROUTER_API_KEY_4 = os.environ.get("OPENROUTER_API_KEY_4", "")
