# Homebrew formula for Relay.
#
# Install with:
#   brew install https://raw.githubusercontent.com/Fiqqar/Relay/main/Formula/relay.rb
#
# (A `brew tap` would require the repo to be named `homebrew-Relay`; see the
# README for instructions on keeping a tap up to date.)
#
# Released by `sdist` from the GitHub Release, built into a virtualenv.
class Relay < Formula
  include Language::Python::Virtualenv

  desc "Your Git workflow, on autopilot: AI Conventional Commits with a manual fallback."
  homepage "https://github.com/Fiqqar/Relay"
  url "https://github.com/Fiqqar/Relay/releases/download/v0.4.0/relay_cli-0.4.0.tar.gz"
  sha256 "2ce6ac46853251b402827a707238765930422564b82dcb09874450cd958cc074"
  license "MIT"
  head "https://github.com/Fiqqar/Relay.git", branch: "main"

  depends_on "python3"

  def install
    # Zero runtime dependencies, so a plain pip install into the formula's
    # virtualenv is enough — no post-install steps.
    virtualenv_install_with_resources
  end

  test do
    assert_match "relay #{version}", shell_output("#{bin}/relay --version")
  end
end