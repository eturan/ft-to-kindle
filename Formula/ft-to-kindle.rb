# Homebrew formula for ft-to-kindle. Lives in the tap repo
# github.com/eturan/homebrew-tap as Formula/ft-to-kindle.rb; this copy is
# the source of truth. Bump url/sha256 on each release
# (`brew fetch --build-from-source ./Formula/ft-to-kindle.rb` prints the sha).
class FtToKindle < Formula
  include Language::Python::Virtualenv

  desc "Your myFT feed on your Kindle every morning"
  homepage "https://github.com/eturan/ft-to-kindle"
  url "https://github.com/eturan/ft-to-kindle/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_TARBALL_SHA256"
  license "GPL-3.0-or-later"
  head "https://github.com/eturan/ft-to-kindle.git", branch: "main"

  # Homebrew python links OpenSSL 3.x, which FT's bot protection requires.
  depends_on "python@3.13"
  depends_on cask: "calibre"

  resource "stkclient" do
    url "https://files.pythonhosted.org/packages/source/s/stkclient/stkclient-0.1.1.tar.gz"
    sha256 "REPLACE"
  end
  resource "rsa" do
    url "https://files.pythonhosted.org/packages/source/r/rsa/rsa-4.9.1.tar.gz"
    sha256 "REPLACE"
  end
  resource "pyasn1" do
    url "https://files.pythonhosted.org/packages/source/p/pyasn1/pyasn1-0.6.1.tar.gz"
    sha256 "REPLACE"
  end
  resource "defusedxml" do
    url "https://files.pythonhosted.org/packages/source/d/defusedxml/defusedxml-0.7.1.tar.gz"
    sha256 "REPLACE"
  end
  resource "browser-cookie3" do
    url "https://files.pythonhosted.org/packages/source/b/browser-cookie3/browser-cookie3-0.20.1.tar.gz"
    sha256 "REPLACE"
  end
  resource "lz4" do
    url "https://files.pythonhosted.org/packages/source/l/lz4/lz4-4.4.4.tar.gz"
    sha256 "REPLACE"
  end
  resource "pycryptodomex" do
    url "https://files.pythonhosted.org/packages/source/p/pycryptodomex/pycryptodomex-3.23.0.tar.gz"
    sha256 "REPLACE"
  end

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Finish setting up with:
        ft2k setup
      It needs an FT subscription, an Amazon account with a Kindle, and a
      browser on this Mac that is signed in to ft.com.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/ft2k --version")
  end
end
