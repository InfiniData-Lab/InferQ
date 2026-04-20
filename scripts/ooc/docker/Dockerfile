FROM postgres:16

# Copy config template; entrypoint substitutes CAP_GB at container start.
COPY postgresql.conf.template /etc/pg/postgresql.conf.template
COPY pg_entrypoint.sh /usr/local/bin/pg_entrypoint.sh
RUN chmod +x /usr/local/bin/pg_entrypoint.sh

ENTRYPOINT ["/usr/local/bin/pg_entrypoint.sh"]
CMD ["postgres", "-c", "config_file=/etc/pg/postgresql.conf"]
