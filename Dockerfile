FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    ZN_AGENT_HOME=/var/lib/zn

WORKDIR /opt/zn
COPY runtime/python /opt/zn/runtime/python
RUN python -m pip install --no-cache-dir /opt/zn/runtime/python \
    && useradd --create-home --uid 10001 zn \
    && mkdir -p /var/lib/zn \
    && chown -R zn:zn /var/lib/zn

USER zn
ENTRYPOINT ["python", "-m", "zn_agent.core.resident_server"]
