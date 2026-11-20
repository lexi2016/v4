ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
WORKDIR /work
COPY . research/p515_recovery_v8
RUN python -m pip install --no-cache-dir -r research/p515_recovery_v8/requirements.lock
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
