FROM ubuntu:24.04
# audio.cpp is a prebuilt portable Vulkan distribution; unpack it rather than
# rebuilding, and drop in only what the server needs.
COPY audiocpp_server /usr/local/bin/audiocpp_server
COPY audiocpp_gguf /usr/local/bin/audiocpp_gguf
COPY libggml*.so* /usr/local/lib/
COPY models /models
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg libvulkan1 mesa-vulkan-drivers libopenblas0 \
    && rm -rf /var/lib/apt/lists/*
ENV LD_LIBRARY_PATH=/usr/local/lib AUDIOCPP_CONFIG=/etc/audiocpp/server.json RADV_PERFTEST=nogttspill
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/audiocpp_server"]
