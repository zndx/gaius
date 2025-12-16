"""Simple test flow for verifying metadata service integration."""

from gaius.flows.config import apply_metaflow_config

# Apply config BEFORE importing metaflow - this also applies the 404 patch
apply_metaflow_config("local")

from metaflow import FlowSpec, step


class SimpleTestFlow(FlowSpec):
    """Minimal flow to test metadata service integration."""

    @step
    def start(self):
        """Start step."""
        print("Starting simple test flow")
        self.message = "Hello from Metaflow!"
        self.next(self.end)

    @step
    def end(self):
        """End step."""
        print(f"Ending flow: {self.message}")
        print("Flow completed successfully!")


if __name__ == "__main__":
    SimpleTestFlow()
