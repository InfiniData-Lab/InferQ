FROM postgres:12.22

# Install gettext-base for envsubst (used by pg_entrypoint.sh to substitute
# CAP_GB-derived memory sizes into postgresql.conf at container start).
RUN apt-get update && apt-get install -y --no-install-recommends gettext-base \
    && rm -rf /var/lib/apt/lists/*

# Copy config template; entrypoint substitutes CAP_GB at container start.
COPY postgresql.conf.template /etc/pg/postgresql.conf.template
COPY pg_entrypoint.sh /usr/local/bin/pg_entrypoint.sh
RUN chmod +x /usr/local/bin/pg_entrypoint.sh

ENTRYPOINT ["/usr/local/bin/pg_entrypoint.sh"]
CMD ["postgres", "-c", "config_file=/etc/pg/postgresql.conf"]
