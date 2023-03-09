# This file is responsible for configuring your application
# and its dependencies with the aid of the Mix.Config module.
#
# This configuration file is loaded before any dependency and
# is restricted to this project.

# General application configuration
use Mix.Config

# Configures the endpoint
config :gaius, GaiusWeb.Endpoint,
  url: [host: "localhost"],
  secret_key_base: "1X9xoYaXTte4Z6Fab2LFD4B0p4J3lx3nOYCie4ir5Rc8EisQgpMULrjncm/VpmGx",
  render_errors: [view: GaiusWeb.ErrorView, accepts: ~w(html json), layout: false],
  pubsub_server: Gaius.PubSub,
  live_view: [signing_salt: "kqx4uwws"]

# Configures Elixir's Logger
config :logger, :console,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

# Use Jason for JSON parsing in Phoenix
config :phoenix, :json_library, Jason

# Import environment specific config. This must remain at the bottom
# of this file so it overrides the configuration defined above.
import_config "#{Mix.env()}.exs"
