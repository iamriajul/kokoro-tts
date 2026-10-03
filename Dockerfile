# GPU-accelerated Kokoro TTS, served by audio.cpp.
#
# audio.cpp is used as a prebuilt portable Vulkan distribution rather than
# rebuilt from source: the upstream release already ships a Linux x64 Vulkan
# tarball, and its Vulkan kernel build is slow enough that rebuilding in CI
# would dominate the workflow runtime.
#
# The Kokoro GGUF is fetched at build time rather than committed — ~190 MB is
# too large for git, and it must come from the audio-cpp Hugging Face org
# specifically. Copies mirrored elsewhere do not embed the audio.cpp model
# spec, and audiocpp_server rejects those with:
#   "GGUF ... does not embed an audio.cpp model spec"

FROM ubuntu:24.04

# ASSETS_DIR is populated by CI before the build; see .github/workflows/container.yml
COPY audiocpp/ /tmp/acpp/
COPY models/ /models/

RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg libvulkan1 mesa-vulkan-drivers libopenblas0; \
    rm -rf /var/lib/apt/lists/*; \
    install -Dm755 /tmp/acpp/audiocpp_server /usr/local/bin/audiocpp_server; \
    install -Dm755 /tmp/acpp/audiocpp_gguf   /usr/local/bin/audiocpp_gguf; \
    # shared ggml backends; libggml-vulkan.so is what makes the GPU path work
    for lib in /tmp/acpp/libggml*.so*; do install -Dm755 "$lib" "/usr/local/lib/$(basename "$lib")"; done; \
    rm -rf /tmp/acpp

ENV LD_LIBRARY_PATH=/usr/local/lib \
    AUDIOCPP_CONFIG=/etc/audiocpp/server.json \
    RADV_PERFTEST=nogttspill

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1



# audiocpp_server does not read AUDIOCPP_CONFIG from the environment; it
# requires an explicit --config argument or it exits immediately.
ENTRYPOINT ["/usr/local/bin/audiocpp_server", "--config", "/etc/audiocpp/server.json"]