# Worker runtime for OOC experiments. The orchestrator runs one of these per
# (circuit, cap, engine) triple under `docker run --memory=cap`. The worker
# code, circuit files, and InfiniQuantumSim are bind-mounted at runtime; the
# image only carries Python and the engine libraries.
FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libgomp1: OpenMP runtime needed by qiskit-aer.
# procps: ps/free for diagnostic poking from inside the container.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY worker-requirements.txt /tmp/worker-requirements.txt
RUN pip install --no-cache-dir -r /tmp/worker-requirements.txt

# Repo (InferQ + Infinidata-rdbms-simulator) is bind-mounted by the orchestrator
# at runtime; PYTHONPATH and WORKDIR are set on the docker run command line.
ENTRYPOINT ["python"]
