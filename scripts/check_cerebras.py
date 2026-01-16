import os
from cerebras.cloud.sdk import Cerebras

client = Cerebras(
  api_key=os.environ.get("CEREBRAS_API_KEY"),
)

chat_completion = client.chat.completions.create(
  messages=[
  {"role": "user", "content": "Why is fast inference important?",}
],
  model="zai-glm-4.7",
)
print(chat_completion)

