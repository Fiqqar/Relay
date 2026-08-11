# Homebrew formula for Relay.
#
# Install with (Homebrew >= 6 requires formulae to come from a tap, not a URL):
#   brew tap Fiqqar/relay https://github.com/Fiqqar/Relay
#   brew install Fiqqar/relay/relay
#
# (A conventional `brew tap Fiqqar/relay` alone would require the repo to be
# named `homebrew-relay`; the explicit URL above sidesteps that.)
#
# Released by `sdist` from the GitHub Release, built into a virtualenv.
class Relay < Formula
  include Language::Python::Virtualenv

  desc "Your Git workflow, on autopilot: AI Conventional Commits with a manual fallback."
  homepage "https://github.com/Fiqqar/Relay"
  url "https://github.com/Fiqqar/Relay/releases/download/v0.5.2/relay_cli-0.5.2.tar.gz"
  sha256 "8915891a66eab704b240c2d829fd46eb85d7979248ddeb99f0a58702f1cdab9f"
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