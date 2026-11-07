FROM andrius/asterisk:22@sha256:d6333b8b331563c5887b98b12da9371ef48317e657d17d81770fe085f335041d
COPY entrypoint.sh /usr/local/bin/voice-support-entrypoint
COPY modules.conf /etc/asterisk/modules.conf
RUN chmod +x /usr/local/bin/voice-support-entrypoint
ENTRYPOINT ["/usr/local/bin/voice-support-entrypoint"]
