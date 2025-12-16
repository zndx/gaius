import os
from bytez import Bytez

# insert your key
API_KEY = os.getenv("BYTEZ_API_KEY")
sdk = Bytez(API_KEY)

# choose your model
#model = sdk.model("mistralai/Mistral-Small-24B-Instruct-2501")
model = sdk.model("mistralai/Mistral-7B-Instruct-v0.2")

# provide the model with input
input = [
  {
    "role": "system",
    "content": "You are a friendly chatbot"
  },
  {
    "role": "user",
    "content": "Hello, what is your name?"
  },
  {
    "role": "assistant",
    "content": "Hello, my name is "
  }
]

# send to the model
result = model.run(input)

# observe the output
print({"error": result.error, "output": result.output})

