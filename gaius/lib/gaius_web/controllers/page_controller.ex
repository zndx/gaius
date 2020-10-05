defmodule GaiusWeb.PageController do
  use GaiusWeb, :controller

  def index(conn, _params) do
    render(conn, "index.html")
  end
end
