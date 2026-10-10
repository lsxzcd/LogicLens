# LogicLens submission container
#
# The topic guide requires the submission to be a container built on the
# organiser's base image, running in an offline sandbox and doing the whole
# read-question-to-produce-code job itself (guide 3.1.2). The guide states that
# the base image and the EDA toolchain are fixed by the organiser, and that the
# base image name will be published later, so it is a build argument here:
# filling it in is a one-line change once it is known.
#
#   docker build --build-arg BASE_IMAGE=<official-image> -t logiclens .
#
# The organiser's image is expected to already carry Vivado / Vitis (guide
# 3.1.3.2 lists "基础镜像与 EDA 工具链（只提供 Vivado / Vitis）" as fixed), so this
# Dockerfile does not install them. It installs what the base image is not
# documented to provide, and copies the submission in.
#
# Two build variants are supported, because the guide leaves the model choice to
# the team (3.1.3.2) and the choice determines whether weights travel inside the
# image or on a mounted volume:
#
#   default            weights on a mounted volume at /models (small image)
#   --build-arg BUNDLE_MODEL=1
#                      weights copied into the image (self-contained, large)
#
# See serve/README-zh.md for why the mounted volume is the default.

ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# The organiser's image may or may not define these; declaring them makes the
# rest of the file independent of that detail.
ARG DEBIAN_FRONTEND=noninteractive
ARG BUNDLE_MODEL=0
ARG MODEL_NAME=qwen2.5-coder:1.5b
ARG PYTHON_MIN=3.11

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Runtime dependencies. The agent itself uses only the Python standard library
# (requirements.txt is intentionally empty), so nothing is installed for it.
# What is needed is a Python 3.11+ interpreter, bash, and an inference server.
#
# `ca-certificates` and `curl` are build-time conveniences only; the runtime
# path performs no network access.
RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        apt-get install -y --no-install-recommends \
            bash ca-certificates curl python3 python3-venv; \
        rm -rf /var/lib/apt/lists/*; \
    else \
        echo "base image has no apt-get; assuming python3 and bash are present"; \
    fi

# Fail the build early if the interpreter is too old, rather than at run time.
RUN python3 - <<'PY'
import sys
minimum = (3, 11)
if sys.version_info < minimum:
    sys.exit(f"python {sys.version_info[:2]} is older than the required {minimum}")
print("python", ".".join(map(str, sys.version_info[:3])), "is acceptable")
PY

WORKDIR /opt/logiclens

# Copy the submission. .dockerignore keeps run artifacts and the vendored
# dataset export out, so a build does not depend on local scratch state.
COPY agent/            ./agent/
COPY skill/            ./skill/
COPY serve/            ./serve/
COPY vivado/           ./vivado/
COPY tools/            ./tools/
COPY tests/            ./tests/
COPY experiments/*.py  ./experiments/
COPY model/            ./model/
COPY run.py run.sh run_baseline.py run_baseline.sh eval.py requirements.txt ./
COPY README.md REPORT.md CONTRIBUTING.md ./

# Fix the mode of the shell entry points. Git on Windows cannot record the
# executable bit, so a checkout on that platform lands as 0644 and the container
# would fail with "Permission denied" when it tries to run the entry point.
RUN chmod +x serve/start.sh serve/fetch-model.sh serve/entrypoint.sh run.sh run_baseline.sh

# The weights live on a mounted volume by default, so this image ships without
# them and serve/entrypoint.sh verifies their presence before the agent runs.
# The directory is created here so the default path always exists.
#
# For the self-contained variant use Dockerfile.bundled, which copies the
# weights in; it is a separate file because the weights are several GB and
# should not be part of an ordinary build context.
RUN mkdir -p /models

# By default the weights arrive on a mounted volume, so the image ships without
# them and start.sh verifies their presence before the agent runs.
ENV OLLAMA_MODELS=/models \
    LOGICLENS_MODEL_NAME=${MODEL_NAME} \
    LOGICLENS_MODEL_URL=http://127.0.0.1:11434/v1 \
    LOGICLENS_TEMPERATURE=0.2 \
    LOGICLENS_TOP_P=0.95 \
    LOGICLENS_MAX_TOKENS=2048 \
    LOGICLENS_TIMEOUT=300 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The container must produce code by itself, so the default command starts the
# inference service and then runs the single-question entry point the guide
# specifies. The caller supplies the question path.
#
#   docker run --rm -v /host/models:/models -v "$PWD/task:/task" logiclens \
#       /task/question.txt
#
# `run.sh` is the judged entry point and reads the question path as $1.
ENTRYPOINT ["/opt/logiclens/serve/entrypoint.sh"]
CMD ["/task/question.txt"]
