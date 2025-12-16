"""Check Bytez API models.

Lists available models from Bytez API for chat tasks.
Requires BYTEZ_API_KEY environment variable.
"""

import os
import requests

url = "https://api.bytez.com/models/v2/list/models?task=chat"

api_key = os.environ.get("BYTEZ_API_KEY")
if not api_key:
    print("Error: BYTEZ_API_KEY environment variable not set")
    exit(1)

headers = {"Authorization": api_key}

response = requests.get(url, headers=headers)

print(response.text)

