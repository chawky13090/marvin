FROM debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends xorriso ca-certificates \
    && rm -rf /var/lib/apt/lists/*

USER 65534:65534
ENTRYPOINT ["xorriso"]

