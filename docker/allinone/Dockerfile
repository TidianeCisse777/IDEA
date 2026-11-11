# Image tout-en-un du warehouse NeoLab : PostgreSQL/PostGIS, la base NeoLab (restaurée au premier démarrage),
# le serveur MCP (DbHub et le relais warehouse_connect.py) et un compte de lecture. Sur l'ordinateur, seul
# Docker est requis; l'assistant lance le serveur MCP par `docker exec -i neolab-warehouse neolab-mcp`.
#
# Contexte de construction : le dossier de la copie partagée, qui contient IDEA/ (le code) et la sauvegarde
# neolab_warehouse_*.dump. installer.sh et installer_windows.bat le construisent :
#     docker build -t neolab-warehouse -f IDEA/docker/allinone/Dockerfile .
# PostgreSQL 16 (as the warehouse) on Debian 12: Python 3.11 and Node 18 for the scripts and DbHub, PostGIS
# from the PostgreSQL apt repository the image already uses. (postgis/postgis:16-3.4 is Debian 11: Node 12.)
FROM postgres:16-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-postgis-3 postgresql-16-postgis-3-scripts python3 python3-venv nodejs npm ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PGDATA=/var/lib/postgresql/data/pgdata \
    POSTGRES_USER=neolab \
    POSTGRES_DB=neolab_warehouse \
    NEOLAB_STATE=/var/lib/postgresql/data/neolab

COPY IDEA /opt/neolab/IDEA
RUN python3 -m venv /opt/neolab/venv \
 && /opt/neolab/venv/bin/pip install --no-cache-dir --disable-pip-version-check "psycopg[binary]" python-dotenv \
 && cd /opt/neolab/IDEA \
 && /opt/neolab/venv/bin/python scripts/warehouse_connect.py install-dbhub \
 && /opt/neolab/venv/bin/python scripts/warehouse_connect.py workspace /opt/neolab/workspace \
 && install -m 755 docker/allinone/entrypoint.sh /usr/local/bin/neolab-entrypoint \
 && install -m 755 docker/allinone/initdb.sh /docker-entrypoint-initdb.d/50_neolab.sh \
 && install -m 755 docker/allinone/neolab-mcp /usr/local/bin/neolab-mcp \
 && install -m 755 docker/allinone/neolab-check /usr/local/bin/neolab-check

COPY neolab_warehouse_*.dump /opt/neolab/neolab.dump

HEALTHCHECK --interval=15s --timeout=10s --start-period=30m \
  CMD test -f "$NEOLAB_STATE/ready" && pg_isready -q -h 127.0.0.1 -U neolab -d neolab_warehouse
ENTRYPOINT ["neolab-entrypoint"]
CMD ["postgres", "-c", "logging_collector=on", "-c", "log_destination=csvlog", \
     "-c", "log_filename=postgresql-%Y-%m-%d.log", "-c", "log_rotation_age=1d", "-c", "log_rotation_size=0"]
